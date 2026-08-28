import asyncio
from datetime import datetime, timezone, date
import json
from sqlalchemy import select
from models import Branch, SaleSnapshot, User
from database import engine, AsyncSessionLocal, init_db, Base
from routers.dashboard import aggregate_dashboard, get_history
from pydantic import BaseModel
import uuid
import os

class DummyUser:
    def __init__(self, id, is_superadmin, branch_ids):
        self.id = id
        self.is_superadmin = is_superadmin
        self.branch_ids = branch_ids

class DummyReq(BaseModel):
    dates: list[str]

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSessionLocal() as db:
        b = Branch(name="divado", company_id=1, is_active=True, device_id="123")
        db.add(b)
        await db.commit()
        await db.refresh(b)
        
        metrics = {"cat1": 10}
        snap = SaleSnapshot(
            branch_id=b.id, day_id=1001, gross_total=5000, 
            disc_value=0, disc_lines_value=0, net_total=5000,
            visa_total=1000, takeaway_count=5, takeaway_total=2500,
            delivery_count=5, delivery_total=2500, dlv_service_total=50,
            order_count=10, metrics_json=metrics,
            snapshot_time=datetime.now(timezone.utc).replace(tzinfo=None),
            business_date="2026-08-27"
        )
        db.add(snap)
        await db.commit()
        
        user = DummyUser(id=1, is_superadmin=True, branch_ids=[b.id])
        
        print("Testing Aggregate...")
        req = DummyReq(dates=["2026-08-27"])
        try:
            res_agg = await aggregate_dashboard(req, db=db, current_user=user)
            print("Aggregate OK:", res_agg.grand_gross_total)
        except Exception as e:
            print("Aggregate ERROR:", repr(e))
            
        print("Testing History...")
        try:
            res_hist = await get_history(month="2026-08", db=db, current_user=user)
            print("History OK:", len(res_hist['days']), "days found")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("History ERROR:", repr(e))

asyncio.run(main())
