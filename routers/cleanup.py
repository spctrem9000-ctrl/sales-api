from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from database import get_db

router = APIRouter(prefix="/cleanup", tags=["cleanup"])

@router.get("/fix_orphans")
async def fix_orphans(db: AsyncSession = Depends(get_db)):
    from models import Branch, User
    # Find branches with no users
    branches = (await db.execute(select(Branch))).scalars().all()
    users = (await db.execute(select(User))).scalars().all()
    
    fixed = 0
    for b in branches:
        res = await db.execute(text("SELECT COUNT(*) FROM user_branches WHERE branch_id = :bid"), {"bid": b.id})
        count = res.scalar()
        if count == 0:
            for u in users:
                # PostgreSQL specific on conflict ignore
                try:
                    await db.execute(text("INSERT INTO user_branches (user_id, branch_id) VALUES (:uid, :bid)"), {"uid": u.id, "bid": b.id})
                except:
                    pass
            fixed += 1
            
    await db.commit()
    return {"status": "ok", "fixed_orphans": fixed}

@router.get("/remove_duplicates")
async def remove_duplicates(db: AsyncSession = Depends(get_db)):
    from models import Branch, SaleSnapshot
    result = await db.execute(select(Branch).order_by(Branch.id.asc()))
    branches = result.scalars().all()
    
    seen = {}
    deleted = 0
    for b in branches:
        if not b.device_id: continue
        if b.device_id in seen:
            await db.execute(delete(SaleSnapshot).where(SaleSnapshot.branch_id == b.id))
            await db.execute(text("DELETE FROM user_branches WHERE branch_id = :bid"), {"bid": b.id})
            await db.execute(delete(Branch).where(Branch.id == b.id))
            deleted += 1
        else:
            seen[b.device_id] = b
            
    await db.commit()
    return {"status": "ok", "deleted_duplicate_branches": deleted}
