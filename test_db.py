import asyncio
from sqlalchemy import select, func
from models import Branch, SaleSnapshot, User
from database import engine, AsyncSessionLocal, Base

async def main():
    async with AsyncSessionLocal() as db:
        # Get user 6
        user = (await db.execute(select(User).where(User.id == 6))).scalar_one()
        print(f"User 6 has {len(user.branches)} branches")
        branch_ids = [b.id for b in user.branches]
        print(f"Branch IDs: {branch_ids}")
        
        # Test subquery
        subq = (
            select(SaleSnapshot.branch_id, func.max(SaleSnapshot.id).label("max_id"))
            .join(Branch, Branch.id == SaleSnapshot.branch_id)
            .where(
                Branch.id.in_(branch_ids)
            )
            .group_by(SaleSnapshot.branch_id)
            .subquery()
        )
        
        # Execute subq
        res = await db.execute(select(subq))
        print(f"Subquery returned: {res.all()}")
        
        # Execute main query
        result = await db.execute(
            select(Branch, SaleSnapshot)
            .join(SaleSnapshot, Branch.id == SaleSnapshot.branch_id)
            .join(subq, SaleSnapshot.id == subq.c.max_id)
            .where(Branch.id.in_(branch_ids))
        )
        rows = result.all()
        print(f"Main query returned {len(rows)} rows")

asyncio.run(main())
