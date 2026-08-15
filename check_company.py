import asyncio
from database import engine
from models import Company
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Company))
        for c in res.scalars():
            print(f"Company: {c.name}, Expiry: {c.expiry_date}, tzinfo: {getattr(c.expiry_date, 'tzinfo', None)}")

asyncio.run(check())
