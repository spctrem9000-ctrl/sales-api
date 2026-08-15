import asyncio
from database import AsyncSessionLocal, init_db
from models import Company

async def insert_company():
    await init_db()
    async with AsyncSessionLocal() as db:
        new_company = Company(name="Test Company", api_key="0d751a508c694defb8c774804988782c")
        db.add(new_company)
        await db.commit()

asyncio.run(insert_company())
