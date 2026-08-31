import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from auth import get_current_user
from models import User

DEBUG_ENDPOINTS_ENABLED = os.getenv("DEBUG_ENDPOINTS", "false").lower() == "true"

router = APIRouter()

async def get_super_admin(current_user: User = Depends(get_current_user)):
    if not DEBUG_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    from fastapi import status
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin privileges required."
        )
    return current_user

@router.get("/fix-db")
async def fix_db(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    try:
        await db.execute(text("ALTER TABLE alerts ALTER COLUMN ih_serial TYPE VARCHAR(50);"))
        await db.execute(text("ALTER TABLE alerts ALTER COLUMN is_read TYPE BOOLEAN USING CASE WHEN is_read=1 THEN TRUE ELSE FALSE END;"))
        await db.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@router.get("/check-db")
async def check_db(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    res = await db.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'alerts';"))
    return {"columns": {r[0]: r[1] for r in res.fetchall()}}

@router.post("/test-500")
async def test_500(payload: dict, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    from schemas import SyncAlertsPayload
    from routers.sync import sync_alerts
    from fastapi import BackgroundTasks
    import traceback
    try:
        p = SyncAlertsPayload(**payload)
        bg = BackgroundTasks()
        await sync_alerts(p, bg, db, "0d751a508c694defb8c774804988782c")
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.get("/check-fcm")
async def check_fcm(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    import firebase_admin
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from models import User
    
    users = await db.execute(select(User).options(selectinload(User.branches)))
    user_tokens = [{"username": u.username, "token": u.fcm_token, "superadmin": u.is_superadmin, "branches": [{"id": b.id, "name": b.name} for b in u.branches]} for u in users.scalars().all()]
    
    return {
        "firebase_apps_count": len(firebase_admin._apps),
        "user_tokens": user_tokens
    }

@router.get("/test-fcm")
async def test_fcm_push(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    from firebase_admin import messaging
    from sqlalchemy import select
    from models import User
    import asyncio
    import traceback
    
    users = await db.execute(select(User).where(User.fcm_token != None, User.is_superadmin == False))
    tokens = list(set([u.fcm_token for u in users.scalars().all() if u.fcm_token]))
    
    if not tokens:
        return {"error": "No tokens found"}
        
    try:
        msg = messaging.MulticastMessage(
            notification=messaging.Notification(
                title="Test Push Notification",
                body="This is a test from the server",
            ),
            data={"action": "test"},
            tokens=tokens,
        )
        response = await asyncio.to_thread(messaging.send_each_for_multicast, msg)
        
        failed_tokens = []
        if response.failure_count > 0:
            responses = response.responses
            for idx, resp in enumerate(responses):
                if not resp.success:
                    failed_tokens.append({"token": tokens[idx], "error": str(resp.exception)})
                    
        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "failed_tokens": failed_tokens
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.get('/check-branches')
async def check_branches(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    from sqlalchemy import select
    from models import Branch
    res = await db.execute(select(Branch.id, Branch.name, Branch.max_disc_perc))
    return [{"id": b.id, "name": b.name, "max_disc_perc": b.max_disc_perc} for b in res.all()]
