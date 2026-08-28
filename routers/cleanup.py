from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from database import get_db

router = APIRouter(prefix="/cleanup", tags=["cleanup"])

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
