import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from database import AsyncSessionLocal
from models import Company, User
from push_notifications import send_push_notification

async def check_expirations():
    """Runs daily to check company subscriptions."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                
                # Check for expired companies to suspend
                result = await db.execute(
                    select(Company).where(Company.is_active == True, Company.expiry_date != None)
                )
                companies = result.scalars().all()
                
                for company in companies:
                    exp_date = company.expiry_date.replace(tzinfo=timezone.utc)
                    if exp_date < now:
                        company.is_active = False
                        
                    # Check for 2-day reminder
                    elif company.auto_remind:
                        days_left = (exp_date - now).days
                        if days_left == 2:
                            # Send reminder to users of this company
                            users_result = await db.execute(select(User).where(User.company_id == company.id))
                            users = users_result.scalars().all()
                            for u in users:
                                if u.fcm_token:
                                    await send_push_notification(
                                        u.fcm_token, 
                                        "إشعار انتهاء اشتراك", 
                                        f"نود تنبيهكم بأن اشتراك شركتكم قد ينتهي في ({exp_date.strftime('%Y-%m-%d')}). يرجى التواصل مع الدعم الفني."
                                    )
                
                await db.commit()
                
        except Exception as e:
            print(f"Error in background task check_expirations: {e}")
            
        # Wait 24 hours
        await asyncio.sleep(86400)

async def check_offline_branches():
    """Runs periodically to notify users if a branch goes offline."""
    from models import Branch
    from routers.dashboard import ONLINE_THRESHOLD_MINUTES
    
    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
                
                # Fetch active branches
                result = await db.execute(select(Branch).where(Branch.is_active == True))
                branches = result.scalars().all()
                
                for branch in branches:
                    if branch.last_seen:
                        branch_last_seen = branch.last_seen.replace(tzinfo=timezone.utc)
                        is_offline = branch_last_seen < cutoff
                        
                        if is_offline and not branch.offline_notified:
                            # Went offline, notify users
                            users_result = await db.execute(
                                select(User).options(selectinload(User.branches)).where(
                                    or_(User.company_id == branch.company_id, User.is_superadmin == True)
                                )
                            )
                            users = users_result.scalars().all()
                            for u in users:
                                # Check if user has access to this branch
                                if u.is_superadmin or branch.id in [b.id for b in u.branches]:
                                    if u.fcm_token:
                                        await send_push_notification(
                                            u.fcm_token,
                                            "تحذير: انقطاع الاتصال",
                                            f"الفرع '{branch.name}' غير متصل بالإنترنت ولم يرسل بيانات منذ أكثر من {ONLINE_THRESHOLD_MINUTES} دقائق."
                                        )
                            branch.offline_notified = True
                            
                        elif not is_offline and branch.offline_notified:
                            # Came back online
                            users_result = await db.execute(
                                select(User).options(selectinload(User.branches)).where(
                                    or_(User.company_id == branch.company_id, User.is_superadmin == True)
                                )
                            )
                            users = users_result.scalars().all()
                            for u in users:
                                if u.is_superadmin or branch.id in [b.id for b in u.branches]:
                                    if u.fcm_token:
                                        await send_push_notification(
                                            u.fcm_token,
                                            "تم استعادة الاتصال",
                                            f"الفرع '{branch.name}' عاد للاتصال بالإنترنت بنجاح."
                                        )
                            branch.offline_notified = False
                            
                await db.commit()
                
        except Exception as e:
            print(f"Error in background task check_offline_branches: {e}")
            
        # Check every 30 seconds
        await asyncio.sleep(30)

