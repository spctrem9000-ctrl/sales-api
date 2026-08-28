from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from database import get_db

router = APIRouter(prefix="/cleanup", tags=["cleanup"])

@router.get("/fix_orphans")
async def fix_orphans(db: AsyncSession = Depends(get_db)):
    from models import Branch, User, SaleSnapshot
    branches = (await db.execute(select(Branch))).scalars().all()
    users = (await db.execute(select(User))).scalars().all()
    
    fixed = 0
    debug_info = {"users": [], "branches": []}
    
    for u in users:
        debug_info["users"].append({
            "id": u.id, "username": u.username, "superadmin": u.is_superadmin, "company_id": u.company_id
        })
        
    for b in branches:
        res = await db.execute(text("SELECT user_id FROM user_branches WHERE branch_id = :bid"), {"bid": b.id})
        assigned_users = [r[0] for r in res.all()]
        
        snap_count = (await db.execute(text("SELECT COUNT(*) FROM sale_snapshots WHERE branch_id = :bid"), {"bid": b.id})).scalar()
        
        debug_info["branches"].append({
            "id": b.id, "name": b.name, "device_id": b.device_id, 
            "company_id": b.company_id, "users": assigned_users, "snapshots": snap_count
        })
        
        if not assigned_users:
            for u in users:
                try:
                    await db.execute(text("INSERT INTO user_branches (user_id, branch_id) VALUES (:uid, :bid)"), {"uid": u.id, "bid": b.id})
                except:
                    pass
            fixed += 1
            
    await db.commit()
    debug_info["status"] = "ok"
    debug_info["fixed_orphans"] = fixed
    return debug_info

@router.get("/debug2")
async def debug2(db: AsyncSession = Depends(get_db)):
    from models import Branch, SaleSnapshot, User
    from sqlalchemy import select, func
    
    # 1. Fetch user 6
    user = (await db.execute(select(User).where(User.id == 6))).scalar_one_or_none()
    if not user:
        return {"error": "user 6 not found"}
        
    res = await db.execute(text("SELECT branch_id FROM user_branches WHERE user_id = 6"))
    branch_ids = [r[0] for r in res.all()]
    
    # 2. Subquery
    subq = (
        select(SaleSnapshot.branch_id, func.max(SaleSnapshot.id).label("max_id"))
        .join(Branch, Branch.id == SaleSnapshot.branch_id)
        .where(
            Branch.id.in_(branch_ids)
        )
        .group_by(SaleSnapshot.branch_id)
        .subquery()
    )
    
    # 3. Exec subq
    subq_res = await db.execute(select(subq))
    subq_rows = [{"branch_id": r[0], "max_id": r[1]} for r in subq_res.all()]
    
    # 4. Main query
    result = await db.execute(
        select(Branch, SaleSnapshot)
        .join(SaleSnapshot, Branch.id == SaleSnapshot.branch_id)
        .join(subq, SaleSnapshot.id == subq.c.max_id)
        .where(Branch.id.in_(branch_ids))
    )
    rows = result.all()
    
    return {
        "user_branch_ids": branch_ids,
        "subq_rows": subq_rows,
        "main_rows_count": len(rows),
        "rows": [{"branch_id": b.id, "snap_id": s.id} for b, s in rows]
    }
    
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
