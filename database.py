import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ── Database URL resolution ───────────────────────────────────────────────────
# Railway injects DATABASE_URL automatically.
# Locally we fall back to SQLite (no C/Rust compiler needed).

_raw_url = os.getenv("DATABASE_URL", "")

if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# If no external DB is configured, use local SQLite
DATABASE_URL = _raw_url if _raw_url else "sqlite+aiosqlite:///./sales_monitor.db"

from sqlalchemy import pool
import uuid

# Set connect_args conditionally based on the dialect
kwargs = {}
if "postgresql" in DATABASE_URL:
    kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
    }
    kwargs["poolclass"] = pool.NullPool
elif "sqlite" in DATABASE_URL:
    kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(
    DATABASE_URL, 
    echo=False, 
    **kwargs
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    from models import Branch, SaleSnapshot, User, Alert  # noqa: F401 - ensure models registered
    
    # 1. Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # 2. Safe migrations (run each in its own transaction so one failure doesn't rollback others)
    from sqlalchemy import text
    
    migrations = [
        "ALTER TABLE sale_snapshots ADD visa_total FLOAT DEFAULT 0.0;",
        "ALTER TABLE sale_snapshots ADD takeaway_count INTEGER DEFAULT 0;",
        "ALTER TABLE sale_snapshots ADD takeaway_total FLOAT DEFAULT 0.0;",
        "ALTER TABLE sale_snapshots ADD delivery_count INTEGER DEFAULT 0;",
        "ALTER TABLE sale_snapshots ADD delivery_total FLOAT DEFAULT 0.0;",
        "ALTER TABLE sale_snapshots ADD dlv_service_total FLOAT DEFAULT 0.0;",
        "ALTER TABLE sale_snapshots ADD metrics_json TEXT;",
        "ALTER TABLE sale_snapshots ADD business_date VARCHAR(50);",
        "ALTER TABLE branches ADD max_disc_perc FLOAT DEFAULT 5.0;",
        "ALTER TABLE branches ADD is_active BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE alerts ADD ih_serial BIGINT DEFAULT 0;",
        "ALTER TABLE alerts ALTER COLUMN ih_serial BIGINT;",
        "ALTER TABLE users ADD is_superadmin BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE users ADD company_id INTEGER REFERENCES companies(id);",
        "ALTER TABLE branches ADD company_id INTEGER REFERENCES companies(id);",
        "ALTER TABLE alerts ADD company_id INTEGER REFERENCES companies(id);",
        "ALTER TABLE alerts ADD total FLOAT DEFAULT 0.0;",
        "ALTER TABLE alerts ADD disc_val FLOAT DEFAULT 0.0;",
        "ALTER TABLE alerts ADD net_val FLOAT DEFAULT 0.0;",
        "UPDATE sale_snapshots SET business_date = TO_CHAR(snapshot_time, 'YYYY-MM-DD') WHERE business_date IS NULL;",
        "INSERT INTO user_branches (user_id, branch_id) SELECT u.id, b.id FROM users u JOIN branches b ON u.company_id = b.company_id WHERE u.is_superadmin = FALSE ON CONFLICT DO NOTHING;"
    ]
    
    for query in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(query))
        except Exception:
            # Column already exists or other error, ignore and continue
            pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
