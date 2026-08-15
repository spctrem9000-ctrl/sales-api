import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import LoginRequest, TokenResponse
from auth import verify_password, hash_password, create_access_token
from encryption import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)

# ── Bootstrap: create owner account on first run ────────────────────────────

OWNER_USERNAME = os.getenv("OWNER_USERNAME", "admin")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    result = await db.execute(select(User).options(selectinload(User.company)).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
        
    if not user.is_superadmin and user.company:
        from datetime import datetime, timezone, timedelta
        if not user.company.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your company account is suspended.")
        egypt_now = datetime.now(timezone.utc) + timedelta(hours=3)
        if user.company.expiry_date and user.company.expiry_date <= egypt_now.replace(tzinfo=None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your company subscription has expired.")

    token = create_access_token({"sub": user.username})
    return TokenResponse(access_token=token, is_superadmin=user.is_superadmin)

from auth import get_current_user
from schemas import FCMTokenRequest

@router.post("/fcm-token")
async def update_fcm_token(
    payload: FCMTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.fcm_token = payload.fcm_token
    await db.commit()
    return {"status": "ok", "message": "FCM token updated."}

import firebase_admin
from firebase_admin import messaging

@router.post("/test-fcm")
async def test_fcm(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """مسار تجريبي لإرسال إشعار لكل الأجهزة المسجلة"""
    users_res = await db.execute(select(User).where(User.fcm_token != None))
    tokens = [u.fcm_token for u in users_res.scalars().all() if u.fcm_token]
    
    if not tokens:
        return {"status": "error", "message": "لم يتم العثور على أي أجهزة مسجلة (لا يوجد Token في قاعدة البيانات)"}
        
    if not firebase_admin._apps:
        return {"status": "error", "message": "Firebase لم يتم تهيئته (serviceAccountKey.json مفقود أو به خطأ)"}
        
    try:
        msg = messaging.MulticastMessage(
            notification=messaging.Notification(
                title="تجربة الإشعارات 🚀",
                body="إذا وصلك هذا الإشعار، فنظام الإشعارات يعمل بنجاح!"
            ),
            tokens=tokens,
        )
        response = messaging.send_each_for_multicast(msg)
        return {
            "status": "success", 
            "message": f"تم الإرسال لـ {len(tokens)} جهاز",
            "success_count": response.success_count,
            "failure_count": response.failure_count
        }
    except Exception as e:
        return {"status": "error", "message": f"خطأ في الإرسال: {str(e)}"}
