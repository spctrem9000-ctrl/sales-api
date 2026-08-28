from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Branch, SaleSnapshot, User
from schemas import DashboardResponse, BranchSummary
from auth import get_current_user
from encryption import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)

ONLINE_THRESHOLD_MINUTES = 5


from models import Alert
from schemas import BranchSetting, BranchSettingUpdate, AlertResponse
import json

def _parse_metrics(m) -> dict:
    if not m: return {}
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except:
            return {}
    if isinstance(m, dict):
        return m
    return {}

def merge_metrics(m1: dict | None, m2: dict | None) -> dict:
    m1 = _parse_metrics(m1)
    m2 = _parse_metrics(m2)
    if not m1 and not m2: return {}
    if not m1: return m2.copy()
    if not m2: return m1.copy()
    
    res = m1.copy()
    for k, v in m2.items():
        if isinstance(v, dict):
            res[k] = merge_metrics(res.get(k, {}), v)
        elif isinstance(v, list):
            res[k] = res.get(k, []) + v
        elif isinstance(v, (int, float)):
            res[k] = res.get(k, 0) + v
    return res

def format_metrics(metrics: dict) -> dict:
    metrics = _parse_metrics(metrics)
    if not metrics: return metrics
    
    ts = metrics.get('top_sellers')
    if isinstance(ts, dict):
        valid_ts = {k: int(float(v)) for k, v in ts.items() if isinstance(v, (int, float, str)) and str(v).replace('.','',1).isdigit()}
        metrics['top_sellers'] = dict(sorted(valid_ts.items(), key=lambda item: item[1], reverse=True)[:5])
        
    hs = metrics.get('hourly_sales')
    if isinstance(hs, dict):
        valid_hs = {k: float(v) for k, v in hs.items() if isinstance(v, (int, float, str)) and str(v).replace('.','',1).isdigit()}
        metrics['hourly_sales'] = valid_hs
        
    hsr = metrics.get('hourly_sales_raw')
    if isinstance(hsr, dict):
        valid_hsr = {k: float(v) for k, v in hsr.items() if isinstance(v, (int, float, str)) and str(v).replace('.','',1).isdigit()}
        metrics['hourly_sales_raw'] = valid_hsr

    ti = metrics.get('top_invoices')
    if isinstance(ti, list):
        valid_ti = [x for x in ti if isinstance(x, dict) and "total" in x]
        metrics['top_invoices'] = sorted(valid_ti, key=lambda x: float(x["total"]), reverse=True)[:5]
        
    return metrics

from typing import Optional

@router.get("", response_model=DashboardResponse)
@router.get("/", response_model=DashboardResponse)
async def get_dashboard(
    date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the latest shift snapshot for each branch.
    """
    online_cutoff = datetime.now(timezone.utc) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)

    # 1. Latest Data
    subq = (
        select(SaleSnapshot.branch_id, func.max(SaleSnapshot.id).label("max_id"))
        .join(Branch, Branch.id == SaleSnapshot.branch_id)
        .where(
            Branch.id.in_(current_user.branch_ids) if not current_user.is_superadmin else True
        )
        .group_by(SaleSnapshot.branch_id)
        .subquery()
    )

    result = await db.execute(
        select(Branch, SaleSnapshot)
        .join(SaleSnapshot, Branch.id == SaleSnapshot.branch_id)
        .join(subq, SaleSnapshot.id == subq.c.max_id)
        .where(Branch.id.in_(current_user.branch_ids) if not current_user.is_superadmin else True)
    )
    rows = result.all()

    # --- DEBUG LOGGING ---
    try:
        with open("dashboard_debug.txt", "w", encoding="utf-8") as f:
            f.write(f"USER: {current_user.username} (ID: {current_user.id})\n")
            f.write(f"SUPERADMIN: {current_user.is_superadmin}\n")
            f.write(f"BRANCH_IDS: {current_user.branch_ids}\n")
            f.write(f"DATE ARG: {date}\n")
            f.write(f"ROWS COUNT: {len(rows)}\n")
    except Exception:
        pass
    # ---------------------

    # We will skip last week's data for trends since we are looking at arbitrary latest shifts
    branches: list[BranchSummary] = []
    grand_gross = 0.0
    grand_disc = 0.0
    grand_disc_l = 0.0
    grand_net = 0.0
    grand_visa = 0.0
    grand_takeaway_count = 0
    grand_takeaway_total = 0.0
    grand_delivery_count = 0
    grand_delivery_total = 0.0
    grand_dlv_service_total = 0.0
    total_orders = 0
    grand_metrics = {}

    branch_map = {}
    for b, snap in rows:
        if b.id not in branch_map:
            branch_map[b.id] = {"branch": b, "snaps": []}
        branch_map[b.id]["snaps"].append(snap)

    synced_ids = {b.id for b, _ in rows}

    for b_data in branch_map.values():
        branch = b_data["branch"]
        snaps = b_data["snaps"]
        
        is_online = (
            branch.last_seen is not None
            and branch.last_seen.replace(tzinfo=timezone.utc) >= online_cutoff
        )
        
        b_gross = sum(s.gross_total for s in snaps)
        b_disc = sum(s.disc_value for s in snaps)
        b_disc_lines = sum(s.disc_lines_value for s in snaps)
        b_net = sum(s.net_total for s in snaps)
        b_visa = sum(s.visa_total for s in snaps)
        b_takeaway_count = sum(s.takeaway_count for s in snaps)
        b_takeaway_total = sum(s.takeaway_total for s in snaps)
        b_delivery_count = sum(s.delivery_count for s in snaps)
        b_delivery_total = sum(s.delivery_total for s in snaps)
        b_dlv_service = sum(s.dlv_service_total for s in snaps)
        b_orders = sum(s.order_count for s in snaps)

        b_metrics = {}
        for s in snaps:
            b_metrics = merge_metrics(b_metrics, s.metrics_json)
            
        b_metrics = format_metrics(b_metrics)

        branches.append(
            BranchSummary(
                branch_name=branch.name,
                day_id=snaps[0].day_id if snaps else None,
                business_date=snaps[0].business_date if snaps else None,
                gross_total=b_gross,
                disc_value=b_disc,
                disc_lines_value=b_disc_lines,
                net_total=b_net,
                visa_total=b_visa,
                takeaway_count=b_takeaway_count,
                takeaway_total=b_takeaway_total,
                delivery_count=b_delivery_count,
                delivery_total=b_delivery_total,
                dlv_service_total=b_dlv_service,
                order_count=b_orders,
                avg_order_value=(b_gross / b_orders) if b_orders > 0 else 0.0,
                last_sync=branch.last_seen,
                is_online=is_online,
                metrics=b_metrics,
                trend_perc=None
            )
        )

        grand_gross += b_gross
        grand_disc += b_disc
        grand_disc_l += b_disc_lines
        grand_net += b_net
        grand_visa += b_visa
        grand_takeaway_count += b_takeaway_count
        grand_takeaway_total += b_takeaway_total
        grand_delivery_count += b_delivery_count
        grand_delivery_total += b_delivery_total
        grand_dlv_service_total += b_dlv_service
        total_orders += b_orders
        grand_metrics = merge_metrics(grand_metrics, b_metrics)

    # 3. Add Offline Branches
    if current_user.is_superadmin:
        all_branches_q = select(Branch)
    else:
        all_branches_q = select(Branch).where(Branch.id.in_(current_user.branch_ids))
        
    all_branches = (await db.execute(all_branches_q)).scalars().all()
    
    for branch in all_branches:
        if branch.id not in synced_ids:
            is_online = (
                branch.last_seen is not None
                and branch.last_seen.replace(tzinfo=timezone.utc) >= online_cutoff
            )
            branches.append(
                BranchSummary(
                    branch_name=branch.name,
                    day_id=None,
                    business_date=None,
                    gross_total=0.0,
                    disc_value=0.0,
                    disc_lines_value=0.0,
                    net_total=0.0,
                    visa_total=0.0,
                    takeaway_count=0, takeaway_total=0.0,
                    delivery_count=0, delivery_total=0.0,
                    dlv_service_total=0.0,
                    order_count=0,
                    avg_order_value=0.0,
                    last_sync=branch.last_seen,
                    is_online=is_online,
                    metrics=b_metrics,
                    trend_perc=None
                )
            )

    grand_metrics = format_metrics(grand_metrics)

    import traceback
    try:
        with open("debug_daily.txt", "w", encoding="utf-8") as f:
            f.write(f"USER: {current_user.username} | DATE: {date} | ROWS: {len(rows)} | BRANCHES RET: {len(branches)}\n")
    except Exception as e:
        pass

    return DashboardResponse(
        grand_gross_total=grand_gross,
        grand_disc=grand_disc,
        grand_disc_lines=grand_disc_l,
        grand_net_total=grand_net,
        grand_visa_total=grand_visa,
        grand_takeaway_count=grand_takeaway_count,
        grand_takeaway_total=grand_takeaway_total,
        grand_delivery_count=grand_delivery_count,
        grand_delivery_total=grand_delivery_total,
        grand_dlv_service_total=grand_dlv_service_total,
        total_orders=total_orders,
        branches=branches,
        business_date="آخر وردية (مباشر)",
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        grand_metrics=b_metrics,
        grand_trend_perc=None
    )


from pydantic import BaseModel

class AggregateRequest(BaseModel):
    dates: list[str]

@router.post("/aggregate", response_model=DashboardResponse)
async def aggregate_dashboard(
    req: AggregateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Aggregates dashboard totals for a given list of dates.
    """
    if not req.dates:
        raise HTTPException(status_code=400, detail="No dates provided")

    # 1. Fetch latest snapshot for each branch/day in the given dates
    subq = (
        select(SaleSnapshot.branch_id, SaleSnapshot.day_id, func.max(SaleSnapshot.id).label("max_id"))
        .join(Branch, Branch.id == SaleSnapshot.branch_id)
        .where(
            SaleSnapshot.business_date.in_(req.dates),
            Branch.id.in_(current_user.branch_ids) if not current_user.is_superadmin else True
        )
        .group_by(SaleSnapshot.branch_id, SaleSnapshot.day_id)
        .subquery()
    )

    result = await db.execute(
        select(Branch, SaleSnapshot)
        .join(SaleSnapshot, Branch.id == SaleSnapshot.branch_id)
        .join(subq, SaleSnapshot.id == subq.c.max_id)
        .where(Branch.id.in_(current_user.branch_ids) if not current_user.is_superadmin else True)
    )
    rows = result.all()

    branches: list[BranchSummary] = []
    grand_gross = 0.0
    grand_disc = 0.0
    grand_disc_l = 0.0
    grand_net = 0.0
    grand_visa = 0.0
    grand_takeaway_count = 0
    grand_takeaway_total = 0.0
    grand_delivery_count = 0
    grand_delivery_total = 0.0
    grand_dlv_service_total = 0.0
    total_orders = 0
    grand_metrics = {}

    branch_map = {}
    for b, snap in rows:
        if b.id not in branch_map:
            branch_map[b.id] = {"branch": b, "snaps": []}
        branch_map[b.id]["snaps"].append(snap)

    for b_data in branch_map.values():
        branch = b_data["branch"]
        snaps = b_data["snaps"]
        
        b_gross = sum(s.gross_total for s in snaps)
        b_disc = sum(s.disc_value for s in snaps)
        b_disc_lines = sum(s.disc_lines_value for s in snaps)
        b_net = sum(s.net_total for s in snaps)
        b_visa = sum(s.visa_total for s in snaps)
        b_takeaway_count = sum(s.takeaway_count for s in snaps)
        b_takeaway_total = sum(s.takeaway_total for s in snaps)
        b_delivery_count = sum(s.delivery_count for s in snaps)
        b_delivery_total = sum(s.delivery_total for s in snaps)
        b_dlv_service = sum(s.dlv_service_total for s in snaps)
        b_orders = sum(s.order_count for s in snaps)

        b_metrics = {}
        for s in snaps:
            b_metrics = merge_metrics(b_metrics, s.metrics_json)
            
        b_metrics = format_metrics(b_metrics)

        branches.append(
            BranchSummary(
                branch_name=branch.name,
                day_id=None,
                business_date=None,
                gross_total=b_gross,
                disc_value=b_disc,
                disc_lines_value=b_disc_lines,
                net_total=b_net,
                visa_total=b_visa,
                takeaway_count=b_takeaway_count,
                takeaway_total=b_takeaway_total,
                delivery_count=b_delivery_count,
                delivery_total=b_delivery_total,
                dlv_service_total=b_dlv_service,
                order_count=b_orders,
                avg_order_value=(b_gross / b_orders) if b_orders > 0 else 0.0,
                last_sync=branch.last_seen,
                is_online=False, # Doesn't make sense for aggregated past days
                metrics=b_metrics,
                trend_perc=None
            )
        )

        grand_gross += b_gross
        grand_disc += b_disc
        grand_disc_l += b_disc_lines
        grand_net += b_net
        grand_visa += b_visa
        grand_takeaway_count += b_takeaway_count
        grand_takeaway_total += b_takeaway_total
        grand_delivery_count += b_delivery_count
        grand_delivery_total += b_delivery_total
        grand_dlv_service_total += b_dlv_service
        total_orders += b_orders
        grand_metrics = merge_metrics(grand_metrics, b_metrics)

    grand_metrics = format_metrics(grand_metrics)

    import traceback
    try:
        with open("debug_monthly.txt", "w", encoding="utf-8") as f:
            f.write(f"USER: {current_user.username} | DATES: {len(req.dates)} | ROWS: {len(rows)} | BRANCHES RET: {len(branches)}\n")
    except Exception as e:
        pass

    return DashboardResponse(
        grand_gross_total=grand_gross,
        grand_disc=grand_disc,
        grand_disc_lines=grand_disc_l,
        grand_net_total=grand_net,
        grand_visa_total=grand_visa,
        grand_takeaway_count=grand_takeaway_count,
        grand_takeaway_total=grand_takeaway_total,
        grand_delivery_count=grand_delivery_count,
        grand_delivery_total=grand_delivery_total,
        grand_dlv_service_total=grand_dlv_service_total,
        total_orders=total_orders,
        branches=branches,
        business_date=f"{len(req.dates)} Days Selected",
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        grand_metrics=grand_metrics,
        grand_trend_perc=None
    )


@router.get("/history")
async def get_history(
    month: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    جلب مبيعات الأيام السابقة مجمعة باليوم ثم بالفرع.
    يتم استخدام أحدث لقطة لكل وردية في اليوم لضمان دقة الأرقام النهائية.
    """
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        
    subq = (
        select(
            SaleSnapshot.branch_id,
            SaleSnapshot.day_id,
            func.max(SaleSnapshot.id).label("max_id"),
        )
        .join(Branch, Branch.id == SaleSnapshot.branch_id)
        .where(
            SaleSnapshot.business_date.startswith(month),
            Branch.id.in_(current_user.branch_ids) if not current_user.is_superadmin else True
        )
        .group_by(SaleSnapshot.branch_id, SaleSnapshot.day_id)
        .subquery()
    )

    result = await db.execute(
        select(Branch, SaleSnapshot)
        .join(subq, Branch.id == subq.c.branch_id)
        .join(SaleSnapshot, SaleSnapshot.id == subq.c.max_id)
        .where(Branch.id.in_(current_user.branch_ids) if not current_user.is_superadmin else True)
        .order_by(SaleSnapshot.business_date.desc())
    )
    
    rows = result.all()
    daily_data = {}
    
    for branch, snap in rows:
        b_date = snap.business_date
        if b_date not in daily_data:
            daily_data[b_date] = {}
            
        if branch.name not in daily_data[b_date]:
            daily_data[b_date][branch.name] = {
                "branch_name": branch.name,
                "net_total": 0.0, "visa_total": 0.0, 
                "takeaway_total": 0.0, "delivery_total": 0.0, "dlv_service_total": 0.0,
                "order_count": 0, "metrics": {}
            }
            
        daily_data[b_date][branch.name]["net_total"] += snap.net_total
        daily_data[b_date][branch.name]["visa_total"] += snap.visa_total
        daily_data[b_date][branch.name]["takeaway_total"] += snap.takeaway_total
        daily_data[b_date][branch.name]["delivery_total"] += snap.delivery_total
        daily_data[b_date][branch.name]["dlv_service_total"] += snap.dlv_service_total
        daily_data[b_date][branch.name]["order_count"] += snap.order_count
        
        branch_m = snap.metrics_json if snap.metrics_json else {}
        daily_data[b_date][branch.name]["metrics"] = merge_metrics(daily_data[b_date][branch.name]["metrics"], branch_m)

    days_list = []
    for b_date, branches_dict in sorted(daily_data.items(), key=lambda x: x[0], reverse=True):
        day_net = 0.0
        day_visa = 0.0
        day_takeaway = 0.0
        day_delivery = 0.0
        day_dlv_service = 0.0
        day_orders = 0
        day_metrics = {}
        branch_breakdowns = []
        for b_name, b_totals in branches_dict.items():
            day_net += b_totals["net_total"]
            day_visa += b_totals["visa_total"]
            day_takeaway += b_totals["takeaway_total"]
            day_delivery += b_totals["delivery_total"]
            day_dlv_service += b_totals["dlv_service_total"]
            day_orders += b_totals["order_count"]
            b_metrics = format_metrics(b_totals["metrics"])
            day_metrics = merge_metrics(day_metrics, b_metrics)
            
            branch_breakdowns.append({
                "branch_name": b_name,
                "net_total": b_totals["net_total"],
                "visa_total": b_totals["visa_total"],
                "takeaway_total": b_totals["takeaway_total"],
                "delivery_total": b_totals["delivery_total"],
                "dlv_service_total": b_totals["dlv_service_total"],
                "order_count": b_totals["order_count"],
                "metrics": b_metrics,
            })
        
        day_metrics = format_metrics(day_metrics)
        branch_breakdowns.sort(key=lambda x: x["net_total"], reverse=True)
        days_list.append({
            "business_date": b_date,
            "net_total": day_net,
            "visa_total": day_visa,
            "takeaway_total": day_takeaway,
            "delivery_total": day_delivery,
            "dlv_service_total": day_dlv_service,
            "total_orders": day_orders,
            "branches": branch_breakdowns,
            "metrics": day_metrics,
        })
        
    return {"month": month, "days": days_list}


# ── Branches Settings ─────────────────────────────────────────────────────────

@router.get("/branches", response_model=list[BranchSetting])
async def get_branches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    branch_query = select(Branch).order_by(Branch.name)
    if not current_user.is_superadmin:
        branch_query = branch_query.where(Branch.id.in_(current_user.branch_ids))
        
    result = await db.execute(branch_query)
    return [
        BranchSetting(id=b.id, name=b.name, max_disc_perc=b.max_disc_perc, is_active=b.is_active) 
        for b in result.scalars().all()
    ]

@router.put("/branches/{branch_id}", response_model=BranchSetting)
async def update_branch(
    branch_id: int,
    data: BranchSettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    branch_query = select(Branch).where(Branch.id == branch_id)
    if not current_user.is_superadmin:
        branch_query = branch_query.where(Branch.id.in_(current_user.branch_ids))
        
    result = await db.execute(branch_query)
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
        
    branch.max_disc_perc = data.max_disc_perc
    
    # Delete old alerts that no longer qualify
    await db.execute(
        delete(Alert).where(
            Alert.branch_id == branch_id,
            Alert.disc_perc <= data.max_disc_perc
        )
    )
    
    await db.commit()
    return BranchSetting(id=branch.id, name=branch.name, max_disc_perc=branch.max_disc_perc, is_active=branch.is_active)


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts", response_model=list[AlertResponse])
async def get_alerts(
    date: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Alert, Branch).join(Branch, Alert.branch_id == Branch.id)
    if not current_user.is_superadmin:
        query = query.where(Branch.id.in_(current_user.branch_ids))
        
    if date:
        from datetime import datetime, timedelta
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            start_date = f"{date}T06:00:00"
            next_dt = dt + timedelta(days=1)
            end_date = f"{next_dt.strftime('%Y-%m-%d')}T05:59:59"
            query = query.where(Alert.order_date >= start_date, Alert.order_date <= end_date)
        except ValueError:
            query = query.where(Alert.order_date.startswith(date))
        
    result = await db.execute(
        query.order_by(Alert.id.desc()).offset(skip).limit(limit)
    )
    rows = result.all()
    return [
        AlertResponse(
            id=alert.id,
            branch_name=branch.name,
            ih_serial=alert.ih_serial,
            ih_code=alert.ih_code,
            order_date=alert.order_date,
            disc_perc=alert.disc_perc,
            is_read=alert.is_read,
            items=alert.invoice_items,
            created_at=alert.created_at
        ) for alert, branch in rows
    ]

@router.put("/alerts/{alert_id}/read")
async def mark_alert_read(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert:
        if current_user.is_superadmin:
            raise HTTPException(status_code=403, detail="Superadmins do not manage alerts")
        branch_ids = [b.id for b in current_user.branches]
        if alert.branch_id not in branch_ids:
            raise HTTPException(status_code=403, detail="Not authorized to access this alert")
            
        alert.is_read = True
        await db.commit()
    return {"status": "ok"}


@router.put("/alerts/read-all")
async def mark_all_alerts_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmins do not manage alerts")
    
    branch_ids = [b.id for b in current_user.branches]
    if not branch_ids:
        return {"status": "ok"}
        
    await db.execute(
        update(Alert)
        .where(Alert.is_read == False)
        .where(Alert.branch_id.in_(branch_ids))
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


@router.delete("/alerts/read")
async def delete_read_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmins do not manage alerts")
        
    branch_ids = [b.id for b in current_user.branches]
    if not branch_ids:
        return {"status": "ok"}
        
    await db.execute(
        delete(Alert)
        .where(Alert.is_read == True)
        .where(Alert.branch_id.in_(branch_ids))
    )
    await db.commit()
    return {"status": "ok", "message": "Deleted read alerts"}

