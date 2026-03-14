
import asyncio
import asyncpg
import sys
import os
import re
import time

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import inspect, text
from config import DATABASE_URL
from core.database import Base

# Parse connection details from config URL
# Format: postgresql+asyncpg://user:password@host:port/dbname
match = re.match(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", DATABASE_URL)
if not match:
    print(f"Error parsing DATABASE_URL: {DATABASE_URL}")
    sys.exit(1)

DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME = match.groups()

async def ensure_database_exists():
    """Checks if database exists, creates if not."""
    print(f"Checking database '{DB_NAME}' on {DB_HOST}:{DB_PORT}...")
    
    # Connect to default 'postgres' database to perform admin operations
    try:
        sys_conn = await asyncpg.connect(
            user=DB_USER,
            password=DB_PASS,
            database='postgres',
            host=DB_HOST,
            port=DB_PORT
        )
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL server: {e}")
        return False

    try:
        # Check if DB exists
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME
        )
        
        if not exists:
            print(f"Database '{DB_NAME}' does not exist. Creating...")
            await sys_conn.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"✅ Database '{DB_NAME}' created successfully.")
        else:
            print(f"✅ Database '{DB_NAME}' already exists.")

        print(f"Installing extensions in '{DB_NAME}' (Vector support required)...")
        db_conn = await asyncpg.connect(
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            host=DB_HOST,
            port=DB_PORT
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

async def ensure_tables_exist():
    """Checks table structure using SQLAlchemy."""
    print(f"Checking tables in '{DB_NAME}'...")
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    try:
        async with engine.begin() as conn:
            def get_tables(connection):
                inspector = inspect(connection)
                return set(inspector.get_table_names())

            existing_tables = await conn.run_sync(get_tables)
            required_tables = {"review_tasks", "expert_comments", "paper_sections", "agent_rules"}
            missing_tables = required_tables - existing_tables

            if "expert_comments" in existing_tables:
                def get_expert_comment_columns(connection):
                    inspector = inspect(connection)
                    return {c["name"] for c in inspector.get_columns("expert_comments")}

                columns = await conn.run_sync(get_expert_comment_columns)
                expected = {"comment_id", "metric_id", "text", "embedding"}
                if not expected.issubset(columns):
                    legacy_name = f"expert_comments_legacy_{int(time.time())}"
                    print(f"⚠️ Detected legacy expert_comments schema. Renaming to '{legacy_name}' and recreating...")
                    await conn.execute(text(f'ALTER TABLE expert_comments RENAME TO "{legacy_name}"'))
                    existing_tables.remove("expert_comments")
                    missing_tables.add("expert_comments")

            if "agent_rules" in existing_tables:
                def get_agent_rules_columns(connection):
                    inspector = inspect(connection)
                    return {c["name"] for c in inspector.get_columns("agent_rules")}

                columns = await conn.run_sync(get_agent_rules_columns)
                expected = {"id", "rule_id", "content", "updated_at"}
                if not expected.issubset(columns):
                    legacy_name = f"agent_rules_legacy_{int(time.time())}"
                    print(f"⚠️ Detected legacy agent_rules schema. Renaming to '{legacy_name}' and recreating...")
                    await conn.execute(text(f'ALTER TABLE agent_rules RENAME TO \"{legacy_name}\"'))
                    existing_tables.remove("agent_rules")
                    missing_tables.add("agent_rules")

            if missing_tables:
                print(f"⚠️ Missing tables detected: {sorted(missing_tables)}. Creating missing schema...")
                await conn.run_sync(Base.metadata.create_all)
                print("✅ Tables created/verified successfully.")
            else:
                print("✅ Required tables exist.")

            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_sections_paper_chunk ON paper_sections (paper_id, chunk_id)"
                )
            )
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_rules_rule_id ON agent_rules (rule_id)")
            )

            if "review_tasks" in existing_tables:
                def check_columns(connection):
                    inspector = inspect(connection)
                    return [c['name'] for c in inspector.get_columns("review_tasks")]
                
                columns = await conn.run_sync(check_columns)
                required_cols = ['task_id', 'paper_id', 'status', 'result_json']
                missing_cols = [col for col in required_cols if col not in columns]
                
                if missing_cols:
                    print(f"⚠️ Warning: Table exists but might be missing columns: {missing_cols}")
                else:
                    print("✅ Table structure verification passed.")

    except Exception as e:
        print(f"❌ Error checking tables: {e}")
    finally:
        await engine.dispose()

async def main():
    print("--- Database Verification & Initialization ---")
    if await ensure_database_exists():
        await ensure_tables_exist()
    print("--- Done ---")

if __name__ == "__main__":
    asyncio.run(main())
