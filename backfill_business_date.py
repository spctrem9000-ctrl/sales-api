import asyncio
from database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as db:
        # Check if we are using Postgres or SQLite
        engine_name = db.bind.name
        print(f"Engine: {engine_name}")
        
        if engine_name == "postgresql":
            # Postgres syntax
            await db.execute(text("UPDATE sale_snapshots SET business_date = to_char(snapshot_time, 'YYYY-MM-DD') WHERE business_date IS NULL"))
        else:
            # SQLite syntax
            await db.execute(text("UPDATE sale_snapshots SET business_date = strftime('%Y-%m-%d', snapshot_time) WHERE business_date IS NULL"))
            
        await db.commit()
        print("Backfilled business_date successfully.")

asyncio.run(main())
