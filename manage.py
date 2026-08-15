import asyncio
import os
import argparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Import the database configuration
from database import DATABASE_URL, Base
from models import Branch, SaleSnapshot, Alert

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def reset_all_data():
    """يحذف جميع البيانات من قاعدة البيانات (تصفير كامل)"""
    print("جاري مسح جميع البيانات...")
    async with engine.begin() as conn:
        # Drop all tables
        await conn.run_sync(Base.metadata.drop_all)
        # Recreate all tables
        await conn.run_sync(Base.metadata.create_all)
    print("تم تصفير قاعدة البيانات بالكامل بنجاح. النظام جاهز للعمل الحقيقي!")

async def delete_branch(branch_name: str):
    """يحذف فرع معين بجميع بياناته من فواتير وخصومات"""
    print(f"جاري البحث عن الفرع: {branch_name}...")
    async with async_session_maker() as session:
        # Find the branch
        result = await session.execute(text("SELECT id FROM branches WHERE name = :name"), {"name": branch_name})
        branch = result.fetchone()
        
        if not branch:
            print(f"❌ لم يتم العثور على فرع باسم: {branch_name}")
            return
            
        branch_id = branch[0]
        
        # Delete related data
        await session.execute(text("DELETE FROM alerts WHERE branch_id = :id"), {"id": branch_id})
        await session.execute(text("DELETE FROM sale_snapshots WHERE branch_id = :id"), {"id": branch_id})
        await session.execute(text("DELETE FROM branches WHERE id = :id"), {"id": branch_id})
        
        await session.commit()
        print(f"✅ تم حذف الفرع '{branch_name}' وجميع مبيعاته وخصوماته بنجاح.")

async def main():
    parser = argparse.ArgumentParser(description="أداة إدارة قاعدة بيانات نظام المبيعات")
    parser.add_argument("--reset", action="store_true", help="تصفير قاعدة البيانات بالكامل (مسح كل الفروع والمبيعات)")
    parser.add_argument("--delete-branch", type=str, help="مسح فرع معين بجميع بياناته (اكتب اسم الفرع)")
    
    args = parser.parse_args()
    
    if args.reset:
        confirm = input("⚠️ تحذير: هذا الخيار سيمسح جميع البيانات في النظام! هل أنت متأكد؟ (y/n): ")
        if confirm.lower() == 'y':
            await reset_all_data()
        else:
            print("تم الإلغاء.")
    elif args.delete_branch:
        confirm = input(f"⚠️ تحذير: سيتم مسح الفرع '{args.delete_branch}' بجميع مبيعاته! هل أنت متأكد؟ (y/n): ")
        if confirm.lower() == 'y':
            await delete_branch(args.delete_branch)
        else:
            print("تم الإلغاء.")
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())
