
import asyncio
import asyncpg
import sys
import os
import re

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import inspect
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
            # Check if 'review_tasks' table exists
            def check_table(connection):
                inspector = inspect(connection)
                return inspector.has_table("review_tasks")
            
            table_exists = await conn.run_sync(check_table)
            
            if not table_exists:
                print("Table 'review_tasks' missing. Creating schema...")
                await conn.run_sync(Base.metadata.create_all)
                print("✅ Tables created successfully.")
            else:
                print("✅ Table 'review_tasks' exists.")
                
                # Check required columns
                def check_columns(connection):
                    inspector = inspect(connection)
                    return [c['name'] for c in inspector.get_columns("review_tasks")]
                
                columns = await conn.run_sync(check_columns)
                required_cols = ['task_id', 'paper_id', 'status', 'result_json']
                missing = [col for col in required_cols if col not in columns]
                
                if missing:
                    print(f"⚠️ Warning: Table exists but might be missing columns: {missing}")
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
