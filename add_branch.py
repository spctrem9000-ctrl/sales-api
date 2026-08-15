import asyncio
from database import AsyncSessionLocal, engine, init_db
from models import Branch

async def insert_branch():
    await init_db()
    async with AsyncSessionLocal() as db:
        new_branch = Branch(name="ديفادو هايبر وان", api_key="0d751a508c694defb8c774804988782c", max_disc_perc=20.0, is_active=True)
        db.add(new_branch)
        try:
            await db.commit()
        except Exception:
            pass

asyncio.run(insert_branch())
