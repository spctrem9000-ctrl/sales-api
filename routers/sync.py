import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Branch, SaleSnapshot, Company
from schemas import SyncPayload, SyncResponse
from websocket_manager import manager
from encryption import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)


async def get_or_create_branch(db: AsyncSession, branch_name: str, api_key: str) -> Branch:
    """Return existing branch or auto-register it under the correct Company."""
    result = await db.execute(select(Company).where(Company.api_key == api_key))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
        
    if not company.is_active:
        raise HTTPException(status_code=403, detail="Company account is suspended.")
    from datetime import timedelta
    egypt_now = datetime.now(timezone.utc) + timedelta(hours=3)
    if company.expiry_date and company.expiry_date <= egypt_now.replace(tzinfo=None):
        raise HTTPException(status_code=403, detail="Company subscription has expired.")

    result = await db.execute(
        select(Branch).where(Branch.company_id == company.id, Branch.name == branch_name)
    )
    branch = result.scalar_one_or_none()

    if branch is None:
        branch = Branch(name=branch_name, company_id=company.id)
        db.add(branch)
        await db.flush()
        
    return branch


@router.post("/")
async def sync_sales(
    payload: SyncPayload, 
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Desktop agent يرفع snapshot بالمجاميع المالية
    الفرع بيتسجل تلقائياً أول مرة.
    """
    branch = await get_or_create_branch(db, payload.branch_name, x_api_key)
    if not branch.is_active:
        return {"status": "ok", "message": "Branch is inactive.", "is_active": False, "max_disc_perc": branch.max_disc_perc}

    avg = (
        payload.net_total / payload.order_count
        if payload.order_count > 0
        else 0.0
    )

    res = await db.execute(select(SaleSnapshot).where(
        SaleSnapshot.branch_id == branch.id,
        SaleSnapshot.day_id == payload.day_id
    ))
    snapshot = res.scalar_one_or_none()

    if snapshot:
        snapshot.gross_total = payload.gross_total
        snapshot.disc_value = payload.disc_value
        snapshot.disc_lines_value = payload.disc_lines_value
        snapshot.net_total = payload.net_total
        snapshot.visa_total = payload.visa_total
        snapshot.takeaway_count = payload.takeaway_count
        snapshot.takeaway_total = payload.takeaway_total
        snapshot.delivery_count = payload.delivery_count
        snapshot.delivery_total = payload.delivery_total
        snapshot.dlv_service_total = payload.dlv_service_total
        snapshot.order_count = payload.order_count
        snapshot.business_date = payload.business_date
        snapshot.metrics_json = payload.metrics_json
        snapshot.snapshot_time = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        snapshot = SaleSnapshot(
            branch_id=branch.id,
            day_id=payload.day_id,
            gross_total=payload.gross_total,
            disc_value=payload.disc_value,
            disc_lines_value=payload.disc_lines_value,
            net_total=payload.net_total,
            visa_total=payload.visa_total,
            takeaway_count=payload.takeaway_count,
            takeaway_total=payload.takeaway_total,
            delivery_count=payload.delivery_count,
            delivery_total=payload.delivery_total,
            dlv_service_total=payload.dlv_service_total,
            order_count=payload.order_count,
            business_date=payload.business_date,
            metrics_json=payload.metrics_json,
        )
        db.add(snapshot)

    branch.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    # Trigger UI refresh on connected mobile apps
    await manager.broadcast({"event": "refresh_dashboard"})

    return SyncResponse(
        status="ok",
        message=f"✅ '{branch.name}' | صافي: {payload.net_total:,.2f} | أوردرات: {payload.order_count}",
    )

from models import Alert
from schemas import SyncAlertsPayload

import firebase_admin
from firebase_admin import messaging
from models import User

from fastapi import BackgroundTasks

async def send_fcm_notifications(new_alerts_list, branch_name, branch_id):
    from database import get_db
    try:
        async for db in get_db():
            users_res = await db.execute(
                select(User).join(User.branches)
                .where(
                    Branch.id == branch_id, 
                    User.fcm_token != None,
                    User.is_superadmin == False
                )
            )
            tokens = list(set([u.fcm_token for u in users_res.scalars().all() if u.fcm_token]))
            
            if tokens and firebase_admin._apps:
                messages = []
                for a in new_alerts_list:
                    notif_image = "https://sales-api-ngdi.onrender.com/static/notification_image.jpg"
                    msg = messaging.MulticastMessage(
                        notification=messaging.Notification(
                            title=f"⚠️ خصم {a.disc_perc:.1f}%",
                            body=f"فاتورة #{a.ih_code} في فرع {branch_name}",
                            image=notif_image,
                        ),
                        data={
                            "alert_id": str(a.id),
                            "action": "open_alert"
                        },
                        tokens=tokens,
                    )
                    messages.append(msg)
                
                for msg in messages:
                    response = await asyncio.to_thread(messaging.send_each_for_multicast, msg)
                    print(f"FCM Multicast sent: {response.success_count} success, {response.failure_count} failure")
            break
    except Exception as e:
        print(f"Error sending FCM: {e}")

@router.post("/alerts")
async def sync_alerts(
    payload: SyncAlertsPayload, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    يستقبل الفواتير ذات الخصومات ويسجل تنبيه إذا تجاوزت نسبة الخصم المحددة للفرع.
    """
    branch = await get_or_create_branch(db, payload.branch_name, x_api_key)
    if not branch.is_active:
        return {"status": "ok", "message": "Branch is inactive.", "is_active": False, "max_disc_perc": branch.max_disc_perc}
    
    new_alerts_list = []
    has_changes = False
    
    ih_serials = [int(inv.ih_serial) for inv in payload.alerts if inv.disc_perc > branch.max_disc_perc]
    if not ih_serials:
        return SyncResponse(status="ok", message="لا يوجد فواتير تجاوزت نسبة الخصم المحددة.")
        
    res = await db.execute(select(Alert).where(
        Alert.branch_id == branch.id,
        Alert.ih_serial.in_(ih_serials)
    ))
    existing_alerts = {a.ih_serial: a for a in res.scalars().all()}
    
    for inv in payload.alerts:
        if inv.disc_perc > branch.max_disc_perc:
            alert = existing_alerts.get(int(inv.ih_serial))
            if alert:
                if abs(alert.disc_perc - inv.disc_perc) > 0.001 or alert.invoice_items != [item.model_dump() for item in inv.items]:
                    alert.disc_perc = inv.disc_perc
                    alert.disc_val = inv.disc_val
                    alert.net_val = inv.net_val
                    alert.total = inv.total
                    alert.order_date = inv.order_date
                    alert.invoice_items = [item.model_dump() for item in inv.items]
                    alert.is_read = 0
                    has_changes = True
                    new_alerts_list.append(alert)
            else:
                new_alert = Alert(
                    branch_id=branch.id,
                    ih_serial=int(inv.ih_serial),
                    ih_code=inv.ih_code,
                    order_date=inv.order_date,
                    total=inv.total,
                    disc_val=inv.disc_val,
                    disc_perc=inv.disc_perc,
                    net_val=inv.net_val,
                    is_read=0,
                    invoice_items=[item.model_dump() for item in inv.items]
                )
                db.add(new_alert)
                has_changes = True
                new_alerts_list.append(new_alert)
                
    if has_changes:
        await db.commit()
        
    if new_alerts_list:
        background_tasks.add_task(send_fcm_notifications, new_alerts_list, branch.name, branch.id)
        # Trigger UI refresh on connected mobile apps
        await manager.broadcast({"event": "refresh_dashboard"})
        
    return {
        "status": "ok",
        "message": f"Processed {len(payload.alerts)} invoices. Created {len(new_alerts_list)} alerts.",
        "is_active": branch.is_active,
        "max_disc_perc": branch.max_disc_perc
    }


@router.get("/state")
async def get_sync_state(
    branch_name: str, 
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """Returns branch configuration and the current synced state for the month."""
    branch = await get_or_create_branch(db, branch_name, x_api_key)
    branch.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
    
    current_month_str = datetime.now(timezone.utc).strftime("%Y-%m")
    
    # 1. Fetch latest shifts for the branch (last 60 days approx, or just all)
    # We will fetch all shifts to ensure desktop agent can sync history without re-uploading loops
    from sqlalchemy import func
    subq = (
        select(SaleSnapshot.day_id, func.max(SaleSnapshot.id).label("max_id"))
        .where(
            SaleSnapshot.branch_id == branch.id
        )
        .group_by(SaleSnapshot.day_id)
        .subquery()
    )
    result = await db.execute(
        select(SaleSnapshot).join(subq, SaleSnapshot.id == subq.c.max_id)
    )
    snapshots = result.scalars().all()
    
    shifts = {}
    import json
    for s in snapshots:
        day_flag = 0
        if s.metrics_json:
            try:
                metrics = json.loads(s.metrics_json)
                day_flag = 1 if metrics.get("is_closed") else 0
            except:
                pass
        shifts[str(s.day_id)] = {
            "day_id": s.day_id,
            "gross_total": s.gross_total,
            "disc_value": s.disc_value,
            "disc_lines_value": s.disc_lines_value,
            "net_total": s.net_total,
            "visa_total": s.visa_total,
            "takeaway_count": s.takeaway_count,
            "takeaway_total": s.takeaway_total,
            "delivery_count": s.delivery_count,
            "delivery_total": s.delivery_total,
            "dlv_service_total": s.dlv_service_total,
            "order_count": s.order_count,
            "business_date": s.business_date,
            "day_flag": day_flag,
        }

    # 2. Fetch synced alerts ih_serials
    alerts_result = await db.execute(
        select(Alert.ih_serial, Alert.disc_perc).where(Alert.branch_id == branch.id)
    )
    synced_alerts = {str(row.ih_serial): row.disc_perc for row in alerts_result.all()}
    
    await db.commit()
    
    return {
        "max_disc_perc": branch.max_disc_perc,
        "is_active": branch.is_active,
        "shifts": shifts,
        "synced_alerts": synced_alerts
    }


from auth import get_current_user

@router.get("/register-key")
async def generate_key(current_user=Depends(get_current_user)):
    """يولّد API key عشوائي تحطه في config.json بتاع الفرع."""
    return {"api_key": secrets.token_hex(32)}




