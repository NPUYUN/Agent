
import asyncio
import asyncpg
import sys
import os
from urllib.parse import quote_plus, urlsplit, unquote

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

def _mask_db_url(url: str) -> str:
    try:
        normalized = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        s = urlsplit(normalized)
        netloc = s.hostname or ""
        if s.port:
            netloc = f"{netloc}:{s.port}"
        if s.username:
            netloc = f"{s.username}:***@{netloc}"
        return f"postgresql+asyncpg://{netloc}{s.path}"
    except Exception:
        return "postgresql+asyncpg://***"


def _parse_db_url(url: str):
    normalized = (url or "").strip().replace("postgresql+asyncpg://", "postgresql://", 1)
    s = urlsplit(normalized)
    if not s.scheme.startswith("postgresql"):
        raise ValueError("unsupported scheme")
    user = unquote(s.username or "")
    password = unquote(s.password or "")
    host = s.hostname or ""
    port = int(s.port or 5432)
    name = (s.path or "").lstrip("/")
    if not user or not host or not name:
        raise ValueError("missing user/host/dbname")
    return user, password, host, port, name


def _build_db_url_from_env() -> str | None:
    host = os.getenv("DB_HOST", "").strip()
    port = os.getenv("DB_PORT", "").strip()
    name = os.getenv("DB_NAME", "").strip()
    user = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "")
    if not (host and name and user and password):
        return None
    port_val = port or "5432"
    return (
        "postgresql+asyncpg://"
        + quote_plus(user)
        + ":"
        + quote_plus(password)
        + "@"
        + host
        + ":"
        + port_val
        + "/"
        + name
    )

_CORE_TABLES = ("paper_sections", "expert_comments", "review_tasks")
_OPTIONAL_TABLES = ("agent_rules",)
_PUBLIC_SCHEMA = "public"
_REVIEW_STATUS_ENUM = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "TIMEOUT")


async def _try_exec(conn, sql: str, params: dict | None = None):
    try:
        async with conn.begin_nested():
            await conn.execute(text(sql), params or {})
        return True, None
    except Exception as e:
        return False, e


async def _fetch_val(conn, sql: str, params: dict | None = None):
    result = await conn.execute(text(sql), params or {})
    return result.scalar_one_or_none()


async def _fetch_all(conn, sql: str, params: dict | None = None):
    result = await conn.execute(text(sql), params or {})
    return list(result.mappings().all())


async def _current_user_info(conn) -> dict:
    row = await _fetch_all(
        conn,
        """
        SELECT current_user AS user, r.rolsuper AS is_superuser
        FROM pg_roles r
        WHERE r.rolname = current_user
        """,
    )
    return dict(row[0]) if row else {"user": None, "is_superuser": False}


async def _public_tables(conn) -> set[str]:
    rows = await _fetch_all(
        conn,
        "SELECT tablename FROM pg_tables WHERE schemaname = :s",
        {"s": _PUBLIC_SCHEMA},
    )
    return {str(r.get("tablename")) for r in rows if r.get("tablename")}


async def _table_owner(conn, table: str) -> str | None:
    row = await _fetch_all(
        conn,
        """
        SELECT r.rolname AS owner
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_roles r ON r.oid = c.relowner
        WHERE n.nspname = :s AND c.relname = :t
        """,
        {"s": _PUBLIC_SCHEMA, "t": table},
    )
    return str(row[0].get("owner")) if row else None


async def _ddl_allowed(conn, table: str) -> tuple[bool, str]:
    info = await _current_user_info(conn)
    user = str(info.get("user") or "")
    is_super = bool(info.get("is_superuser"))
    owner = await _table_owner(conn, table)
    if is_super:
        return True, f"user={user} superuser=true owner={owner or '?'}"
    if owner and owner == user:
        return True, f"user={user} superuser=false owner={owner}"
    return False, f"user={user} superuser=false owner={owner or '?'}"


async def _columns_pg(conn, table: str) -> dict[str, dict]:
    rows = await _fetch_all(
        conn,
        """
        SELECT
            a.attname AS name,
            pg_catalog.format_type(a.atttypid, a.atttypmod) AS type,
            a.attnotnull AS not_null
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = :s
          AND c.relname = :t
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        {"s": _PUBLIC_SCHEMA, "t": table},
    )
    out: dict[str, dict] = {}
    for r in rows:
        name = str(r.get("name") or "")
        if not name:
            continue
        out[name] = {"name": name, "type": str(r.get("type") or ""), "not_null": bool(r.get("not_null"))}
    return out


async def _indexes_pg(conn, table: str) -> set[str]:
    rows = await _fetch_all(
        conn,
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = :s AND tablename = :t
        """,
        {"s": _PUBLIC_SCHEMA, "t": table},
    )
    return {str(r.get("indexname")) for r in rows if r.get("indexname")}


async def _row_count(conn, table: str) -> int | None:
    try:
        val = await _fetch_val(conn, f"SELECT COUNT(*) FROM {_PUBLIC_SCHEMA}.{table}")
        return int(val) if val is not None else None
    except Exception:
        return None


async def _ensure_enum_task_status(conn):
    ok, err = await _try_exec(
        conn,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') THEN
                CREATE TYPE taskstatus AS ENUM ('PENDING','RUNNING','SUCCESS','FAILED','TIMEOUT');
            END IF;
        END$$;
        """,
    )
    if not ok:
        print(f"⚠️ Failed to ensure enum taskstatus: {type(err).__name__}: {err}")


async def _ensure_table_review_tasks(conn):
    await _ensure_enum_task_status(conn)
    ok, err = await _try_exec(
        conn,
        """
        CREATE TABLE IF NOT EXISTS review_tasks (
            id BIGSERIAL PRIMARY KEY,
            task_id TEXT NOT NULL,
            paper_id UUID NOT NULL,
            chunk_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            agent_version TEXT NOT NULL,
            status taskstatus NOT NULL DEFAULT 'PENDING',
            score INTEGER,
            audit_level TEXT,
            result_json JSONB,
            error_msg TEXT,
            usage_tokens INTEGER,
            latency_ms INTEGER,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
    )
    if not ok:
        print(f"❌ Failed to create review_tasks: {type(err).__name__}: {err}")
        return

    await _try_exec(conn, "CREATE INDEX IF NOT EXISTS ix_review_tasks_task_id ON review_tasks (task_id);")
    await _try_exec(conn, "CREATE INDEX IF NOT EXISTS ix_review_tasks_paper_id ON review_tasks (paper_id);")
    await _try_exec(conn, "CREATE INDEX IF NOT EXISTS ix_review_tasks_paper_chunk ON review_tasks (paper_id, chunk_id);")
    await _try_exec(conn, "ALTER TABLE review_tasks ALTER COLUMN status SET DEFAULT 'PENDING';")
    await _try_exec(conn, "ALTER TABLE review_tasks ALTER COLUMN created_at SET DEFAULT NOW();")
    await _try_exec(conn, "ALTER TABLE review_tasks ALTER COLUMN updated_at SET DEFAULT NOW();")


async def _ensure_table_paper_sections(conn):
    ok, err = await _try_exec(
        conn,
        """
        CREATE TABLE IF NOT EXISTS paper_sections (
            id UUID,
            paper_id UUID NOT NULL,
            chunk_id TEXT NOT NULL,
            section_name TEXT,
            content TEXT NOT NULL,
            metadata_json JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT pk_paper_sections_id PRIMARY KEY (id)
        );
        """,
    )
    if not ok:
        print(f"❌ Failed to create paper_sections: {type(err).__name__}: {err}")
        return

    await _try_exec(conn, "CREATE INDEX IF NOT EXISTS ix_paper_sections_paper_id ON paper_sections (paper_id);")
    await _try_exec(conn, "CREATE INDEX IF NOT EXISTS ix_paper_sections_chunk_id ON paper_sections (chunk_id);")
    await _try_exec(
        conn,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_sections_paper_chunk ON paper_sections (paper_id, chunk_id);",
    )


async def _ensure_table_expert_comments(conn):
    ok, err = await _try_exec(
        conn,
        """
        CREATE TABLE IF NOT EXISTS expert_comments (
            comment_id TEXT PRIMARY KEY,
            metric_id TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding vector(768),
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
    )
    if not ok:
        print(f"❌ Failed to create expert_comments: {type(err).__name__}: {err}")
        return

    await _try_exec(conn, "CREATE INDEX IF NOT EXISTS ix_expert_comments_metric_id ON expert_comments (metric_id);")


async def _ensure_table_agent_rules(conn):
    ok, err = await _try_exec(
        conn,
        """
        CREATE TABLE IF NOT EXISTS agent_rules (
            id BIGSERIAL PRIMARY KEY,
            rule_id TEXT NOT NULL,
            content TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
    )
    if not ok:
        print(f"⚠️ Failed to create agent_rules: {type(err).__name__}: {err}")
        return
    await _try_exec(conn, "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_rules_rule_id ON agent_rules (rule_id);")


def _type_matches(expected: str, actual: str) -> bool:
    e = (expected or "").lower().strip()
    a = (actual or "").lower().strip()
    if not e:
        return True
    if e == "text":
        return ("text" in a) or ("character varying" in a) or ("varchar" in a)
    if e == "timestamp":
        return "timestamp" in a
    if e == "uuid":
        return "uuid" in a
    if e == "integer":
        return ("integer" in a) or ("int" in a)
    if e == "bigint":
        return ("bigint" in a) or ("bigint" == a)
    if e == "jsonb":
        return "jsonb" in a
    if e == "vector":
        return "vector" in a
    if e == "taskstatus":
        return "taskstatus" in a
    return e in a


async def _maybe_fix_review_tasks_status(conn, can_ddl: bool):
    if not can_ddl:
        return
    cols = await _columns_pg(conn, "review_tasks")
    status = cols.get("status")
    if not status:
        return
    if _type_matches("taskstatus", str(status.get("type") or "")):
        return

    cnt = await _row_count(conn, "review_tasks")
    if cnt is None:
        return
    if cnt == 0:
        ok, err = await _try_exec(
            conn,
            """
            ALTER TABLE review_tasks
            ALTER COLUMN status TYPE taskstatus
            USING status::taskstatus
            """,
        )
        if ok:
            print("✅ Fixed review_tasks.status type to taskstatus (table empty).")
        else:
            print(f"⚠️ Failed to fix review_tasks.status type: {type(err).__name__}: {err}")
        return

    vals = await _fetch_all(
        conn,
        "SELECT DISTINCT status::text AS v FROM review_tasks WHERE status IS NOT NULL LIMIT 50",
    )
    distinct = {str(r.get("v") or "") for r in vals}
    if distinct and distinct.issubset(set(_REVIEW_STATUS_ENUM)):
        ok, err = await _try_exec(
            conn,
            """
            ALTER TABLE review_tasks
            ALTER COLUMN status TYPE taskstatus
            USING status::text::taskstatus
            """,
        )
        if ok:
            print("✅ Fixed review_tasks.status type to taskstatus (values compatible).")
        else:
            print(f"⚠️ Failed to fix review_tasks.status type: {type(err).__name__}: {err}")
    else:
        sample = ", ".join(sorted([v for v in distinct if v])[:10])
        print(f"⚠️ review_tasks.status values not compatible with enum: {sample or '?'}")


async def _check_and_patch_table(
    conn,
    table: str,
    required_cols: dict,
    required_indexes: list[tuple[str, list[str], bool]],
    can_ddl: bool,
    ddl_context: str,
):
    cols = await _columns_pg(conn, table)
    missing = [k for k in required_cols.keys() if k not in cols]
    if missing:
        if not can_ddl:
            print(f"⚠️ Skip ADD COLUMN on {table} (no DDL privilege): {ddl_context}")
        else:
            for c in missing:
                ddl = required_cols[c].get("ddl")
                if not ddl:
                    continue
                ok, err = await _try_exec(conn, ddl)
                if ok:
                    print(f"✅ Added column {table}.{c}")
                else:
                    print(f"⚠️ Failed to add column {table}.{c}: {type(err).__name__}: {err}")

    cols = await _columns_pg(conn, table)
    mismatches = []
    for c, expected in required_cols.items():
        if c not in cols:
            continue
        expected_type = expected.get("type")
        if expected_type:
            actual_type = str(cols[c].get("type") or "").lower()
            if not _type_matches(expected_type, actual_type):
                mismatches.append((c, expected_type, actual_type))
    for c, exp, act in mismatches:
        print(f"⚠️ Column type mismatch {table}.{c}: expected contains '{exp}', actual '{act}'")

    existing_names = await _indexes_pg(conn, table)

    for name, cols_list, unique in required_indexes:
        if name in existing_names:
            continue
        if not can_ddl:
            print(f"⚠️ Skip CREATE INDEX {name} on {table} (no DDL privilege): {ddl_context}")
            continue
        cols_sql = ", ".join(cols_list)
        if unique:
            ok, err = await _try_exec(conn, f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({cols_sql});")
        else:
            ok, err = await _try_exec(conn, f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols_sql});")
        if ok:
            print(f"✅ Ensured index {name} on {table}({cols_sql})")
        else:
            print(f"⚠️ Failed to ensure index {name} on {table}: {type(err).__name__}: {err}")


async def ensure_database_exists(db_user: str, db_pass: str, db_host: str, db_port: int, db_name: str):
    """Checks if database exists, creates if not."""
    print(f"Checking database '{db_name}' on {db_host}:{db_port}...")
    
    # Connect to default 'postgres' database to perform admin operations
    try:
        sys_conn = await asyncpg.connect(
            user=db_user,
            password=db_pass,
            database="postgres",
            host=db_host,
            port=db_port,
        )
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL server: {e}")
        return False

    try:
        # Check if DB exists
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            db_name,
        )
        
        if not exists:
            print(f"Database '{db_name}' does not exist. Creating...")
            await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"✅ Database '{db_name}' created successfully.")
        else:
            print(f"✅ Database '{db_name}' already exists.")

        print(f"Installing extensions in '{db_name}' (Vector support required)...")
        db_conn = await asyncpg.connect(
            user=db_user,
            password=db_pass,
            database=db_name,
            host=db_host,
            port=db_port,
        )
        try:
            await db_conn.execute('CREATE EXTENSION IF NOT EXISTS vector;')
            print("✅ Extension 'vector' installed/verified.")
        except Exception as e:
            print(f"❌ Failed to install 'vector' extension on DB server: {e}")
            print("HINT: Install pgvector on the PostgreSQL server (or use the pgvector docker image).")
            return False
        finally:
            await db_conn.close()
            
    except Exception as e:
        print(f"❌ Error checking/creating database: {e}")
        return False
    finally:
        await sys_conn.close()
    
    return True

async def ensure_tables_exist(database_url: str, db_name: str):
    """Checks table structure and patches schema to match 开发规范.md without modifying existing data."""
    print(f"Checking tables in '{db_name}'...")
    
    engine = create_async_engine(database_url, echo=False)
    
    try:
        async with engine.begin() as conn:
            existing_tables = await _public_tables(conn)
            for t in _CORE_TABLES:
                if t not in existing_tables:
                    print(f"⚠️ Missing core table: {t}")
            for t in _OPTIONAL_TABLES:
                if t not in existing_tables:
                    print(f"⚠️ Missing optional table: {t}")

            await _ensure_table_paper_sections(conn)
            await _ensure_table_expert_comments(conn)
            await _ensure_table_review_tasks(conn)
            await _ensure_table_agent_rules(conn)

            can_paper, ctx_paper = await _ddl_allowed(conn, "paper_sections")
            can_expert, ctx_expert = await _ddl_allowed(conn, "expert_comments")
            can_review, ctx_review = await _ddl_allowed(conn, "review_tasks")
            can_rules, ctx_rules = await _ddl_allowed(conn, "agent_rules")

            await _check_and_patch_table(
                conn,
                "paper_sections",
                required_cols={
                    "paper_id": {"type": "uuid", "ddl": "ALTER TABLE paper_sections ADD COLUMN IF NOT EXISTS paper_id UUID;"},
                    "section_name": {"type": "text", "ddl": "ALTER TABLE paper_sections ADD COLUMN IF NOT EXISTS section_name TEXT;"},
                    "content": {"type": "text", "ddl": "ALTER TABLE paper_sections ADD COLUMN IF NOT EXISTS content TEXT;"},
                },
                required_indexes=[
                    ("ix_paper_sections_paper_id", ["paper_id"], False),
                ],
                can_ddl=can_paper,
                ddl_context=ctx_paper,
            )

            await _check_and_patch_table(
                conn,
                "expert_comments",
                required_cols={
                    "comment_id": {"type": "text", "ddl": "ALTER TABLE expert_comments ADD COLUMN IF NOT EXISTS comment_id TEXT;"},
                    "metric_id": {"type": "text", "ddl": "ALTER TABLE expert_comments ADD COLUMN IF NOT EXISTS metric_id TEXT;"},
                    "text": {"type": "text", "ddl": "ALTER TABLE expert_comments ADD COLUMN IF NOT EXISTS text TEXT;"},
                    "embedding": {"type": "vector", "ddl": "ALTER TABLE expert_comments ADD COLUMN IF NOT EXISTS embedding vector(768);"},
                },
                required_indexes=[
                    ("ix_expert_comments_metric_id", ["metric_id"], False),
                ],
                can_ddl=can_expert,
                ddl_context=ctx_expert,
            )

            await _check_and_patch_table(
                conn,
                "review_tasks",
                required_cols={
                    "task_id": {"type": "text", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS task_id TEXT;"},
                    "paper_id": {"type": "uuid", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS paper_id UUID;"},
                    "chunk_id": {"type": "text", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS chunk_id TEXT;"},
                    "agent_name": {"type": "text", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS agent_name TEXT;"},
                    "agent_version": {"type": "text", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS agent_version TEXT;"},
                    "status": {"type": "taskstatus", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS status taskstatus;"},
                    "score": {"type": "integer", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS score INTEGER;"},
                    "audit_level": {"type": "text", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS audit_level TEXT;"},
                    "result_json": {"type": "jsonb", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS result_json JSONB;"},
                    "error_msg": {"type": "text", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS error_msg TEXT;"},
                    "usage_tokens": {"type": "integer", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS usage_tokens INTEGER;"},
                    "latency_ms": {"type": "integer", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS latency_ms INTEGER;"},
                    "created_at": {"type": "timestamp", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;"},
                    "updated_at": {"type": "timestamp", "ddl": "ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;"},
                },
                required_indexes=[
                    ("ix_review_tasks_task_id", ["task_id"], False),
                    ("ix_review_tasks_paper_id", ["paper_id"], False),
                    ("ix_review_tasks_paper_chunk", ["paper_id", "chunk_id"], False),
                ],
                can_ddl=can_review,
                ddl_context=ctx_review,
            )

            await _maybe_fix_review_tasks_status(conn, can_review)

            await _check_and_patch_table(
                conn,
                "agent_rules",
                required_cols={
                    "rule_id": {"type": "text", "ddl": "ALTER TABLE agent_rules ADD COLUMN IF NOT EXISTS rule_id TEXT;"},
                    "content": {"type": "text", "ddl": "ALTER TABLE agent_rules ADD COLUMN IF NOT EXISTS content TEXT;"},
                    "updated_at": {"type": "timestamp", "ddl": "ALTER TABLE agent_rules ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;"},
                },
                required_indexes=[
                    ("uq_agent_rules_rule_id", ["rule_id"], True),
                ],
                can_ddl=can_rules,
                ddl_context=ctx_rules,
            )

            print("✅ Schema verification & patch completed.")

    except Exception as e:
        print(f"❌ Error checking tables: {e}")
    finally:
        await engine.dispose()

async def main():
    print("--- Database Verification & Initialization ---")
    explicit_url = os.getenv("DATABASE_URL", "").strip()
    env_url = _build_db_url_from_env()
    if explicit_url:
        database_url = explicit_url
        source = "env:DATABASE_URL"
    elif env_url:
        database_url = env_url
        source = "env:DB_*"
    else:
        from config import DATABASE_URL as config_url

        database_url = (config_url or "").strip()
        source = "config:DATABASE_URL"

    try:
        db_user, db_pass, db_host, db_port, db_name = _parse_db_url(database_url)
    except Exception:
        print(f"Error parsing DATABASE_URL ({source}): {_mask_db_url(database_url)}")
        raise

    print(f"DB_URL_SOURCE: {source}")
    print(f"DB_URL: {_mask_db_url(database_url)}")

    if await ensure_database_exists(db_user, db_pass, db_host, db_port, db_name):
        await ensure_tables_exist(database_url, db_name)
    print("--- Done ---")

if __name__ == "__main__":
    asyncio.run(main())
