import secrets
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Branch, SaleSnapshot, Company, Alert, User
from schemas import SyncPayload, SyncResponse, SyncAlertsPayload
from websocket_manager import manager
from encryption import EncryptedRoute

import firebase_admin
from firebase_admin import messaging

from auth import get_current_user


router = APIRouter(route_class=EncryptedRoute)

fcm_logger = logging.getLogger("uvicorn.error")


# ============================================================
# BRANCH / DEVICE AUTHENTICATION
# ============================================================

async def get_or_create_branch(
    db: AsyncSession,
    branch_name: str,
    api_key: str,
    device_id: str,
) -> Branch:
    """
    Return existing branch or auto-register it under the correct Company.

    Device binding:
    - New branch -> create it with is_active=False and bind device_id.
    - Existing branch without device_id -> bind the first device.
    - Existing branch with same device_id -> allow.
    - Existing branch with different device_id -> reject.
    """

    # --------------------------------------------------------
    # 1. Validate Company / API Key
    # --------------------------------------------------------

    result = await db.execute(
        select(Company).where(Company.api_key == api_key)
    )

    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key."
        )

    if not company.is_active:
        raise HTTPException(
            status_code=403,
            detail="Company account is suspended."
        )

    # --------------------------------------------------------
    # 2. Check Company subscription
    # --------------------------------------------------------

    from datetime import timedelta

    egypt_now = datetime.now(timezone.utc) + timedelta(hours=3)

    if (
        company.expiry_date
        and company.expiry_date <= egypt_now.replace(tzinfo=None)
    ):
        raise HTTPException(
            status_code=403,
            detail="Company subscription has expired."
        )

    # --------------------------------------------------------
    # 3. Find Branch
    # --------------------------------------------------------

    # Try finding by device_id first (so renaming works)
    result = await db.execute(
        select(Branch).where(
            Branch.company_id == company.id,
            Branch.device_id == device_id
        ).order_by(Branch.id.asc())
    )
    branch = result.scalars().first()

    if not branch:
        # Fallback to name
        result = await db.execute(
            select(Branch).where(
                Branch.company_id == company.id,
                Branch.name == branch_name
            ).order_by(Branch.id.asc())
        )
        branch = result.scalars().first()

    # --------------------------------------------------------
    # 4. New Branch
    # --------------------------------------------------------

    if branch is None:

        branch = Branch(
            name=branch_name,
            company_id=company.id,

            # New branches require manual activation
            is_active=False,

            # Bind first device
            device_id=device_id,
        )

        db.add(branch)

        await db.flush()

        return branch

    # --------------------------------------------------------
    # 5. Existing Branch - No Device Bound Yet
    # --------------------------------------------------------

    if not branch.device_id:

        branch.device_id = device_id

        await db.flush()

    # --------------------------------------------------------
    # 6. Existing Branch - Check Device
    # --------------------------------------------------------

    elif branch.device_id != device_id:

        raise HTTPException(
            status_code=403,
            detail="This device is not authorized for this branch."
        )

    return branch


# ============================================================
# SALES SYNC
# ============================================================

@router.post("/")
async def sync_sales(
    payload: SyncPayload,
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(..., alias="X-API-Key"),
    x_device_id: str = Header(..., alias="X-Device-ID"),
):
    """
    Desktop agent uploads sales snapshot.

    Branch is automatically registered on first sync,
    but starts inactive until manually activated.
    """

    branch = await get_or_create_branch(
        db=db,
        branch_name=payload.branch_name,
        api_key=x_api_key,
        device_id=x_device_id,
    )

    # --------------------------------------------------------
    # Branch inactive
    # --------------------------------------------------------

    if not branch.is_active:

        return {
            "status": "ok",
            "message": "Branch is inactive.",
            "is_active": False,
            "max_disc_perc": branch.max_disc_perc,
        }

    # --------------------------------------------------------
    # Calculate average
    # --------------------------------------------------------

    avg = (
        payload.net_total / payload.order_count
        if payload.order_count > 0
        else 0.0
    )

    # --------------------------------------------------------
    # UPSERT SaleSnapshot
    # --------------------------------------------------------

    values_to_upsert = {
        "branch_id": branch.id,
        "day_id": payload.day_id,
        "gross_total": payload.gross_total,
        "disc_value": payload.disc_value,
        "disc_lines_value": payload.disc_lines_value,
        "net_total": payload.net_total,
        "visa_total": payload.visa_total,
        
        "cash_total": payload.cash_total,
        "wallet_total": payload.wallet_total,
        "insta_total": payload.insta_total,
        "hos_total": payload.hos_total,
        "credit_total": payload.credit_total,
        "visa_tip_total": payload.visa_tip_total,
        "tax_total": payload.tax_total,
        "expenses_total": payload.expenses_total,
        "void_total": payload.void_total,
        
        "takeaway_count": payload.takeaway_count,
        "takeaway_total": payload.takeaway_total,
        "delivery_count": payload.delivery_count,
        "delivery_total": payload.delivery_total,
        "dlv_service_total": payload.dlv_service_total,
        "order_count": payload.order_count,
        "business_date": payload.business_date,
        "metrics_json": payload.metrics_json,
        "snapshot_time": datetime.now(timezone.utc).replace(tzinfo=None)
    }

    from database import engine
    dialect = engine.dialect.name

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(SaleSnapshot).values(**values_to_upsert)
        stmt = stmt.on_conflict_do_update(
            index_elements=["branch_id", "day_id"],
            set_=values_to_upsert
        )
        await db.execute(stmt)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(SaleSnapshot).values(**values_to_upsert)
        stmt = stmt.on_conflict_do_update(
            index_elements=["branch_id", "day_id"],
            set_=values_to_upsert
        )
        await db.execute(stmt)
    else:
        # Fallback for any other dialect (shouldn't happen in production)
        res = await db.execute(
            select(SaleSnapshot).where(
                SaleSnapshot.branch_id == branch.id,
                SaleSnapshot.day_id == payload.day_id
            )
        )
        snapshot = res.scalar_one_or_none()
        if snapshot:
            for k, v in values_to_upsert.items():
                setattr(snapshot, k, v)
        else:
            snapshot = SaleSnapshot(**values_to_upsert)
            db.add(snapshot)

    # --------------------------------------------------------
    # Update last seen
    # --------------------------------------------------------

    branch.last_seen = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
    )

    await db.commit()

    # --------------------------------------------------------
    # Notify connected mobile apps
    # --------------------------------------------------------

    await manager.broadcast_to_company(
        branch.company_id,
        {"event": "refresh_dashboard"}
    )

    return SyncResponse(
        status="ok",
        message=(
            f"✅ '{branch.name}' | "
            f"صافي: {payload.net_total:,.2f} | "
            f"أوردرات: {payload.order_count}"
        ),
    )


# ============================================================
# FCM NOTIFICATIONS
# ============================================================

async def send_fcm_notifications(
    alerts_data: list[dict],
    tokens: list[str],
    branch_name: str,
):
    """
    Send FCM push notifications.
    Receives plain dicts + tokens.
    """

    try:

        if not tokens or not firebase_admin._apps:
            return

        for a in alerts_data:

            notif_image = (
                "https://sales-api-ngdi.onrender.com/"
                "static/notification_image.jpg"
            )

            msg = messaging.MulticastMessage(

                notification=messaging.Notification(
                    title=f"⚠️ خصم {a['disc_perc']:.1f}%",
                    body=f"فاتورة #{a['ih_code']} في فرع {branch_name}",
                    image=notif_image,
                ),

                data={
                    "alert_id": str(a.get("id", 0)),
                    "action": "open_alert"
                },

                tokens=tokens,
            )

            response = await asyncio.to_thread(
                messaging.send_each_for_multicast,
                msg
            )

            fcm_logger.info(
                f"FCM Multicast sent: "
                f"{response.success_count} success, "
                f"{response.failure_count} failure"
            )

            # Log failed tokens
            if response.failure_count > 0:

                for idx, resp in enumerate(response.responses):

                    if not resp.success:

                        fcm_logger.warning(
                            f"FCM failed for token "
                            f"{tokens[idx][:20]}...: "
                            f"{resp.exception}"
                        )

    except Exception as e:

        fcm_logger.error(
            f"Error sending FCM: {e}"
        )


# ============================================================
# ALERTS SYNC
# ============================================================

@router.post("/alerts")
async def sync_alerts(
    payload: SyncAlertsPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(..., alias="X-API-Key"),
    x_device_id: str = Header(..., alias="X-Device-ID"),
):
    """
    Receives discounted invoices and creates alerts
    when discount exceeds branch limit.
    """

    branch = await get_or_create_branch(
        db=db,
        branch_name=payload.branch_name,
        api_key=x_api_key,
        device_id=x_device_id,
    )

    # --------------------------------------------------------
    # Branch inactive
    # --------------------------------------------------------

    if not branch.is_active:

        return {
            "status": "ok",
            "message": "Branch is inactive.",
            "is_active": False,
            "max_disc_perc": branch.max_disc_perc,
        }

    new_alerts_list = []
    has_changes = False

    # --------------------------------------------------------
    # Get invoice serials
    #
    # Supabase alerts.ih_serial = VARCHAR
    # --------------------------------------------------------

    ih_serials = [
        str(inv.ih_serial)
        for inv in payload.alerts
        if inv.disc_perc > branch.max_disc_perc
    ]

    if not ih_serials:

        return SyncResponse(
            status="ok",
            message="لا يوجد فواتير تجاوزت نسبة الخصم المحددة."
        )

    # --------------------------------------------------------
    # Find existing alerts
    # --------------------------------------------------------

    res = await db.execute(
        select(Alert).where(
            Alert.branch_id == branch.id,
            Alert.ih_serial.in_(ih_serials)
        )
    )

    existing_alerts = {
        a.ih_serial: a
        for a in res.scalars().all()
    }

    # --------------------------------------------------------
    # Process alerts
    # --------------------------------------------------------

    for inv in payload.alerts:

        if inv.disc_perc > branch.max_disc_perc:

            alert = existing_alerts.get(
                str(inv.ih_serial)
            )

            # ------------------------------------------------
            # Existing alert
            # ------------------------------------------------

            if alert:

                if (
                    abs(
                        alert.disc_perc -
                        inv.disc_perc
                    ) > 0.001

                    or

                    alert.invoice_items != [
                        item.model_dump()
                        for item in inv.items
                    ]
                ):

                    alert.disc_perc = inv.disc_perc
                    alert.disc_val = inv.disc_val
                    alert.net_val = inv.net_val
                    alert.total = inv.total
                    alert.order_date = inv.order_date

                    alert.invoice_items = [
                        item.model_dump()
                        for item in inv.items
                    ]

                    alert.is_read = False
                    alert.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

                    has_changes = True

                    new_alerts_list.append(alert)

            # ------------------------------------------------
            # New alert (UPSERT to avoid concurrency errors)
            # ------------------------------------------------

            else:

                invoice_items_dump = [
                    item.model_dump()
                    for item in inv.items
                ]

                values_to_upsert = {
                    "branch_id": branch.id,
                    "ih_serial": str(inv.ih_serial),
                    "ih_code": inv.ih_code,
                    "order_date": inv.order_date,
                    "total": inv.total,
                    "disc_val": inv.disc_val,
                    "disc_perc": inv.disc_perc,
                    "net_val": inv.net_val,
                    "is_read": False,
                    "invoice_items": invoice_items_dump,
                    "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
                }
                
                from database import engine
                dialect = engine.dialect.name
                
                if dialect == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    stmt = pg_insert(Alert).values(**values_to_upsert)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["branch_id", "ih_serial"]
                    ).returning(Alert)
                    res = await db.execute(stmt)
                    new_alert = res.scalar_one_or_none()
                    if new_alert:
                        has_changes = True
                        new_alerts_list.append(new_alert)
                elif dialect == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(Alert).values(**values_to_upsert)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["branch_id", "ih_serial"]
                    ).returning(Alert)
                    res = await db.execute(stmt)
                    new_alert = res.scalar_one_or_none()
                    if new_alert:
                        has_changes = True
                        new_alerts_list.append(new_alert)
                else:
                    new_alert = Alert(**values_to_upsert)
                    db.add(new_alert)
                    has_changes = True
                    new_alerts_list.append(new_alert)

    # --------------------------------------------------------
    # Commit changes
    # --------------------------------------------------------

    if has_changes:

        await db.commit()

    # --------------------------------------------------------
    # FCM + mobile refresh
    # --------------------------------------------------------

    if new_alerts_list:

        users_res = await db.execute(

            select(User)
            .join(User.branches)
            .where(
                Branch.id == branch.id,
                User.fcm_token != None,
                User.is_superadmin == False
            )
        )

        tokens = list(
            set(
                [
                    u.fcm_token
                    for u in users_res.scalars().all()
                    if u.fcm_token
                ]
            )
        )

        # Convert ORM objects to plain dictionaries
        alerts_data = [
            {
                "id": a.id,
                "disc_perc": a.disc_perc,
                "ih_code": a.ih_code
            }
            for a in new_alerts_list
        ]

        if tokens:

            background_tasks.add_task(
                send_fcm_notifications,
                alerts_data,
                tokens,
                branch.name
            )

        # Trigger UI refresh
        await manager.broadcast_to_company(
            branch.company_id,
            {"event": "refresh_dashboard"}
        )

    return {
        "status": "ok",
        "message": (
            f"Processed {len(payload.alerts)} invoices. "
            f"Created {len(new_alerts_list)} alerts."
        ),
        "is_active": branch.is_active,
        "max_disc_perc": branch.max_disc_perc
    }


# ============================================================
# SYNC STATE
# ============================================================

@router.get("/state")
async def get_sync_state(
    branch_name: str,
    full_sync: str = "false",
    revision: str = None,
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(..., alias="X-API-Key"),
    x_device_id: str = Header(..., alias="X-Device-ID"),
):
    """
    Returns branch configuration and synced state.
    """

    branch = await get_or_create_branch(
        db=db,
        branch_name=branch_name,
        api_key=x_api_key,
        device_id=x_device_id,
    )

    branch.last_seen = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
    )

    from sqlalchemy import func
    from datetime import timedelta
    import json

    is_full_sync = full_sync.lower() == "true"
    days_back = 31 if is_full_sync else 2
    cutoff_datetime = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_back)
    cutoff_date_str = cutoff_datetime.strftime("%Y-%m-%d")

    # --------------------------------------------------------
    # Calculate Revision ETag
    # --------------------------------------------------------

    agg_res = await db.execute(
        select(
            func.count(SaleSnapshot.id),
            func.max(SaleSnapshot.snapshot_time)
        ).where(
            SaleSnapshot.branch_id == branch.id,
            SaleSnapshot.business_date >= cutoff_date_str
        )
    )
    snap_count, snap_max_time = agg_res.one()

    alert_agg_res = await db.execute(
        select(
            func.count(Alert.id),
            func.max(Alert.updated_at)
        ).where(
            Alert.branch_id == branch.id,
            Alert.created_at >= cutoff_datetime
        )
    )
    alert_count, alert_max_time = alert_agg_res.one()

    snap_max_str = str(snap_max_time) if snap_max_time else "0"
    alert_max_str = str(alert_max_time) if alert_max_time else "0"

    current_revision = f"{snap_count}-{snap_max_str}-{alert_count}-{alert_max_str}-{branch.max_disc_perc}-{branch.is_active}-{full_sync.lower()}"

    if revision == current_revision:
        await db.commit()
        return {
            "is_active": branch.is_active,
            "max_disc_perc": branch.max_disc_perc,
            "changed": False,
            "revision": current_revision
        }

    # --------------------------------------------------------
    # Fetch snapshots (Optimized: No Group By or Subqueries)
    # --------------------------------------------------------

    result = await db.execute(
        select(SaleSnapshot)
        .where(
            SaleSnapshot.branch_id == branch.id,
            SaleSnapshot.business_date >= cutoff_date_str
        )
    )
    snapshots = result.scalars().all()

    shifts = {}

    for s in snapshots:
        day_flag = 0
        if s.metrics_json:
            try:
                if isinstance(s.metrics_json, dict):
                    metrics = s.metrics_json
                else:
                    metrics = json.loads(s.metrics_json)
                day_flag = 0 if metrics.get("is_closed") else 1
            except Exception:
                pass

        shifts[str(s.day_id)] = {
            "day_id": s.day_id,
            "gross_total": s.gross_total,
            "disc_value": s.disc_value,
            "disc_lines_value": s.disc_lines_value,
            "net_total": s.net_total,
            "visa_total": s.visa_total,
            
            "cash_total": s.cash_total,
            "wallet_total": s.wallet_total,
            "insta_total": s.insta_total,
            "hos_total": s.hos_total,
            "credit_total": s.credit_total,
            "visa_tip_total": s.visa_tip_total,
            "tax_total": s.tax_total,
            "expenses_total": s.expenses_total,
            "void_total": s.void_total,
            
            "takeaway_count": s.takeaway_count,
            "takeaway_total": s.takeaway_total,
            "delivery_count": s.delivery_count,
            "delivery_total": s.delivery_total,
            "dlv_service_total": s.dlv_service_total,
            "order_count": s.order_count,
            "business_date": s.business_date,
            "day_flag": day_flag,
        }

    # --------------------------------------------------------
    # Fetch synced alerts
    # --------------------------------------------------------

    base_alerts_query = select(
        Alert.ih_serial,
        Alert.disc_perc
    ).where(
        Alert.branch_id == branch.id,
        Alert.created_at >= cutoff_datetime
    )

    alerts_result = await db.execute(base_alerts_query)

    synced_alerts = {
        str(row.ih_serial): row.disc_perc
        for row in alerts_result.all()
    }

    await db.commit()

    # --------------------------------------------------------
    # Return full state
    # --------------------------------------------------------

    return {
        "max_disc_perc": branch.max_disc_perc,
        "is_active": branch.is_active,
        "shifts": shifts,
        "synced_alerts": synced_alerts,
        "changed": True,
        "revision": current_revision,
    }


# ============================================================
# REGISTER API KEY
# ============================================================

@router.get("/register-key")
async def generate_key(
    current_user=Depends(get_current_user)
):
    """
    Generates a random API key for a branch configuration.
    """

    return {
        "api_key": secrets.token_hex(32)
    }
