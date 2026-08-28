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
@router.get("/debug2")
async def debug2(db: AsyncSession = Depends(get_db)):
    from models import Branch, SaleSnapshot, User
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    
    # 1. Fetch user 6 using selectinload
    user = (await db.execute(select(User).options(selectinload(User.branches)).where(User.id == 6))).scalar_one_or_none()
    if not user:
        return {"error": "user 6 not found"}
        
    branch_ids = user.branch_ids
    
    # 2. Subquery
    subq = (
        select(SaleSnapshot.branch_id, func.max(SaleSnapshot.id).label("max_id"))
        .join(Branch, Branch.id == SaleSnapshot.branch_id)
        .where(
            Branch.id.in_(branch_ids) if branch_ids else False
        )
        .group_by(SaleSnapshot.branch_id)
        .subquery()
    )
    
    # 4. Main query
    result = await db.execute(
        select(Branch, SaleSnapshot)
        .join(SaleSnapshot, Branch.id == SaleSnapshot.branch_id)
        .join(subq, SaleSnapshot.id == subq.c.max_id)
        .where(Branch.id.in_(branch_ids) if branch_ids else False)
    )
    rows = result.all()
    
    return {
        "user_branch_ids": branch_ids,
        "main_rows_count": len(rows),
    }

@router.get("/debug3")
async def debug3(db: AsyncSession = Depends(get_db)):
    from models import Branch, SaleSnapshot, User
    from sqlalchemy import select, func
    from datetime import datetime, timezone, timedelta
    from schemas import BranchSummary
    import json
    
    def format_metrics(metrics_json):
        if not metrics_json: return {}
        if isinstance(metrics_json, str):
            try:
                return json.loads(metrics_json)
            except:
                return {}
        return metrics_json

    user = (await db.execute(select(User).where(User.id == 6))).scalar_one_or_none()
    res = await db.execute(text("SELECT branch_id FROM user_branches WHERE user_id = 6"))
    branch_ids = [r[0] for r in res.all()]
    
    subq = (
        select(SaleSnapshot.branch_id, func.max(SaleSnapshot.id).label("max_id"))
        .join(Branch, Branch.id == SaleSnapshot.branch_id)
        .where(Branch.id.in_(branch_ids) if branch_ids else False)
        .group_by(SaleSnapshot.branch_id)
        .subquery()
    )
    
    result = await db.execute(
        select(Branch, SaleSnapshot)
        .join(SaleSnapshot, Branch.id == SaleSnapshot.branch_id)
        .join(subq, SaleSnapshot.id == subq.c.max_id)
        .where(Branch.id.in_(branch_ids) if branch_ids else False)
    )
    rows = result.all()
    
    branches = []
    online_cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    
    try:
        for b, snap in rows:
            is_online = b.last_seen and b.last_seen.replace(tzinfo=timezone.utc) >= online_cutoff
            b_metrics = format_metrics(snap.metrics_json)
            
            branches.append(
                BranchSummary(
                    branch_name=b.name,
                    day_id=snap.day_id,
                    business_date=snap.business_date,
                    gross_total=snap.gross_total,
                    disc_value=snap.disc_value,
                    disc_lines_value=snap.disc_lines_value,
                    net_total=snap.net_total,
                    visa_total=snap.visa_total,
                    takeaway_count=snap.takeaway_count,
                    takeaway_total=snap.takeaway_total,
                    delivery_count=snap.delivery_count,
                    delivery_total=snap.delivery_total,
                    dlv_service_total=snap.dlv_service_total,
                    order_count=snap.order_count,
                    avg_order_value=(snap.gross_total / snap.order_count) if snap.order_count > 0 else 0.0,
                    last_sync=b.last_seen,
                    is_online=is_online,
                    metrics=b_metrics,
                    trend_perc=None
                ).model_dump()
            )
        return {"status": "ok", "branches": branches}
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}

@router.get("/debug4")
async def debug4(db: AsyncSession = Depends(get_db)):
    from models import User
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(User).options(selectinload(User.company), selectinload(User.branches)).where(User.id == 6)
    )
    user = result.scalars().first()
    
    return {
        "user_id": user.id,
        "branches_loaded": [b.id for b in user.branches],
        "branch_ids_property": user.branch_ids
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
