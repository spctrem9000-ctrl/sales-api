import asyncio
from sqlalchemy import select
from models import Base, User, Branch, user_branches
from database import engine, get_db

async def migrate():
    async with engine.begin() as conn:
        print("Creating new tables...")
        await conn.run_sync(Base.metadata.create_all)
        
    async for db in get_db():
        print("Migrating users...")
        users = await db.execute(select(User).where(User.is_superadmin == False))
        for user in users.scalars().all():
            if user.company_id:
                branches = await db.execute(select(Branch).where(Branch.company_id == user.company_id))
                user.branches = branches.scalars().all()
        await db.commit()
        print("Migration complete!")
        break

asyncio.run(migrate())
