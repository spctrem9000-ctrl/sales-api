import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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
