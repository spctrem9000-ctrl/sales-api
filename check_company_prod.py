import asyncio
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from models import Company

# Production DB string
DATABASE_URL = "postgresql+asyncpg://sales_api_db_5zrt_user:S58a1OtvP0xTfX4X0jP02E0sR80z7g6g@dpg-cqq7g4o8fa8c739mftsg-a.oregon-postgres.render.com/sales_api_db_5zrt"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Company))
        for c in res.scalars():
            print(f"Company: {c.name}, Expiry: {c.expiry_date}, tzinfo: {getattr(c.expiry_date, 'tzinfo', None)}")

asyncio.run(check())
