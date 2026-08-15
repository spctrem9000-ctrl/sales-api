import asyncio
from database import AsyncSessionLocal
from models import Company, User
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Company))
        companies = res.scalars().all()
        for c in companies:
            print(f'Company {c.id}: {c.name}, active={c.is_active}')

asyncio.run(main())
