import asyncio
from sqlalchemy import select
from models import Company
from database import engine, get_db

async def get_key():
    async for db in get_db():
        c = await db.execute(select(Company))
        company = c.scalars().first()
        if company:
            print(f"API_KEY: {company.api_key}")
        break

asyncio.run(get_key())
