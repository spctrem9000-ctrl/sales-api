import asyncio
from database import AsyncSessionLocal, init_db
from sqlalchemy import select
from models import Branch

async def check_branch():
    await init_db()
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Branch))
        for b in res.scalars().all():
            print(f"Branch: {b.name}, max_disc_perc: {b.max_disc_perc}")

asyncio.run(check_branch())
