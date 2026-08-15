import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from fastapi import BackgroundTasks
import json
import os

os.environ['SECRET_KEY'] = 'testsecret'
os.environ['ALGORITHM'] = 'HS256'

from models import Alert, Company
from schemas import SyncAlertsPayload, AlertPayload, InvoiceItemPayload
from routers.sync import sync_alerts, get_or_create_branch

async def test_endpoint():
    from database import engine, AsyncSessionLocal, init_db
    import datetime
    
    await init_db()
    
    async with AsyncSessionLocal() as db:
        c = Company(name="Test", api_key="0d751a508c694defb8c774804988782c", is_active=True)
        db.add(c)
        await db.commit()
    
    payload = SyncAlertsPayload(
        branch_name="Test Branch",
        alerts=[
            AlertPayload(
                ih_serial=1001000225858,
                ih_code="186",
                order_date=datetime.datetime(2026, 8, 3, 1, 7, 1, 353000),
                disc_perc=50.0,
                is_open=False,
                items=[
                    InvoiceItemPayload(name="test", qty=1.0, price=10.0, total=10.0)
                ]
            )
        ]
    )
    
    async with AsyncSessionLocal() as db:
        bg = BackgroundTasks()
        try:
            res = await sync_alerts(payload, bg, db, "0d751a508c694defb8c774804988782c")
            print("SUCCESS:", res)
        except Exception as e:
            import traceback
            traceback.print_exc()

asyncio.run(test_endpoint())
