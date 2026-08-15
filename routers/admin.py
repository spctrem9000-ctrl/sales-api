import uuid
from typing import List, Optional
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from database import get_db
from models import User, Company, Branch, SaleSnapshot
from auth import get_current_user, hash_password
from push_notifications import send_push_notification
from encryption import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)


async def get_super_admin(current_user: User = Depends(get_current_user)):
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin privileges required."
        )
    return current_user


# Schemas
class CompanyCreate(BaseModel):
    name: str
    subscription_date: Optional[date] = None
    expiry_date: Optional[date] = None
    auto_remind: bool = True


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    subscription_date: Optional[date] = None
    expiry_date: Optional[date] = None
    auto_remind: Optional[bool] = None

class CompanyResponse(BaseModel):
    id: int
    name: str
    api_key: str
    is_active: bool
    subscription_date: datetime
    expiry_date: Optional[datetime] = None
    auto_remind: bool
    created_at: datetime


class CompanyStatusUpdate(BaseModel):
    is_active: bool


class UserCreate(BaseModel):
    company_id: int
    username: str
    password: str
    branch_ids: Optional[List[int]] = None

class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    branch_ids: Optional[List[int]] = None

class UserResponse(BaseModel):
    id: int
    username: str
    created_at: datetime
    is_superadmin: bool
    branch_ids: List[int] = []

class BranchResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    is_active: bool
    last_sync: Optional[datetime] = None

class BranchUpdate(BaseModel):
    name: str
    is_active: bool

class NotificationRequest(BaseModel):
    title: str
    body: str

class StatsResponse(BaseModel):
    total_companies: int
    total_branches: int
    active_branches: int
    inactive_branches: int
    total_users: int

# --- STATS ---
@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    comp_count = await db.execute(select(func.count(Company.id)))
    branch_count = await db.execute(select(func.count(Branch.id)))
    active_branch_count = await db.execute(select(func.count(Branch.id)).where(Branch.is_active == True))
    inactive_branch_count = await db.execute(select(func.count(Branch.id)).where(Branch.is_active == False))
    user_count = await db.execute(select(func.count(User.id)).where(User.is_superadmin == False))
    return StatsResponse(
        total_companies=comp_count.scalar() or 0,
        total_branches=branch_count.scalar() or 0,
        active_branches=active_branch_count.scalar() or 0,
        inactive_branches=inactive_branch_count.scalar() or 0,
        total_users=user_count.scalar() or 0
    )


# --- COMPANIES ---
@router.get("/companies", response_model=List[CompanyResponse])
async def get_companies(db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(Company).order_by(Company.created_at.desc()))
    return result.scalars().all()


@router.post("/companies", response_model=CompanyResponse)
async def create_company(payload: CompanyCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    existing = await db.execute(select(Company).where(Company.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Company name already exists.")

    company = Company(
        name=payload.name,
        api_key=uuid.uuid4().hex,
        subscription_date=payload.subscription_date or datetime.utcnow(),
        expiry_date=payload.expiry_date,
        auto_remind=payload.auto_remind
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


@router.put("/companies/{company_id}", response_model=CompanyResponse)
async def update_company(company_id: int, payload: CompanyUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    if payload.name is not None:
        company.name = payload.name
    if payload.subscription_date is not None:
        company.subscription_date = payload.subscription_date
    if payload.expiry_date is not None:
        company.expiry_date = payload.expiry_date
    if payload.auto_remind is not None:
        company.auto_remind = payload.auto_remind
        
    await db.commit()
    await db.refresh(company)
    return company


@router.put("/companies/{company_id}/status")
async def update_company_status(company_id: int, payload: CompanyStatusUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    company.is_active = payload.is_active
    await db.commit()
    return {"status": "ok", "message": f"Company active status set to {payload.is_active}"}


@router.delete("/companies/{company_id}")
async def delete_company(company_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    # 1. Delete all users belonging to the company
    await db.execute(delete(User).where(User.company_id == company_id))
    
    # 2. Get all branches for this company
    res_branches = await db.execute(select(Branch).where(Branch.company_id == company_id))
    branches = res_branches.scalars().all()
    branch_ids = [b.id for b in branches]
    
    if branch_ids:
        # Delete alerts and snapshots for these branches
        from models import Alert, SaleSnapshot
        await db.execute(delete(Alert).where(Alert.branch_id.in_(branch_ids)))
        await db.execute(delete(SaleSnapshot).where(SaleSnapshot.branch_id.in_(branch_ids)))
        # Delete branches
        await db.execute(delete(Branch).where(Branch.company_id == company_id))
    
    # 3. Finally delete the company
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    
    await db.delete(company)
    await db.commit()
    return {"status": "ok", "message": "Company deleted."}


@router.post("/companies/{company_id}/notify")
async def notify_company(company_id: int, payload: NotificationRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(User).where(User.company_id == company_id))
    users = result.scalars().all()
    
    for u in users:
        if u.fcm_token:
            await send_push_notification(u.fcm_token, payload.title, payload.body)
            
    return {"status": "ok", "message": f"Notification sent to {len(users)} devices."}


# --- USERS ---
@router.get("/companies/{company_id}/users", response_model=List[UserResponse])
async def get_company_users(company_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(User).options(selectinload(User.branches)).where(User.company_id == company_id))
    return result.scalars().all()

@router.post("/users")
async def create_company_user(payload: UserCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    comp_result = await db.execute(select(Company).where(Company.id == payload.company_id))
    if not comp_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found.")
        
    user_result = await db.execute(select(User).where(User.username == payload.username))
    if user_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken.")
        
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        company_id=payload.company_id
    )
    if payload.branch_ids:
        branch_res = await db.execute(select(Branch).where(Branch.id.in_(payload.branch_ids), Branch.company_id == payload.company_id))
        user.branches = branch_res.scalars().all()
    db.add(user)
    await db.commit()
    return {"status": "ok", "message": f"User {payload.username} created successfully."}

@router.put("/users/{user_id}")
async def update_user(user_id: int, payload: UserUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(User).options(selectinload(User.branches)).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    if payload.username:
        # Check uniqueness
        exist = await db.execute(select(User).where(User.username == payload.username, User.id != user_id))
        if exist.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already in use.")
        user.username = payload.username
        
    if payload.password:
        user.hashed_password = hash_password(payload.password)
        
    if payload.branch_ids is not None:
        branch_res = await db.execute(select(Branch).where(Branch.id.in_(payload.branch_ids), Branch.company_id == user.company_id))
        user.branches = branch_res.scalars().all()
        
    await db.commit()
    return {"status": "ok", "message": "User updated."}

@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_superadmin:
        raise HTTPException(status_code=403, detail="Cannot delete super admin.")
        
    await db.delete(user)
    await db.commit()
    return {"status": "ok", "message": "User deleted."}


# --- BRANCHES ---
@router.get("/companies/{company_id}/branches", response_model=List[BranchResponse])
async def get_company_branches(company_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(Branch).where(Branch.company_id == company_id))
    branches = result.scalars().all()
    
    # Get last sync time for each branch
    res = []
    for b in branches:
        # Query latest snapshot
        snap = await db.execute(select(SaleSnapshot.snapshot_time).where(SaleSnapshot.branch_id == b.id).order_by(SaleSnapshot.snapshot_time.desc()).limit(1))
        last_sync = snap.scalar_one_or_none()
        res.append(BranchResponse(
            id=b.id,
            name=b.name,
            created_at=b.created_at,
            is_active=b.is_active,
            last_sync=last_sync
        ))
    return res

@router.put("/branches/{branch_id}")
async def update_branch(branch_id: int, payload: BranchUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(Branch).where(Branch.id == branch_id))
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found.")
        
    branch.name = payload.name
    branch.is_active = payload.is_active
    await db.commit()
    return {"status": "ok", "message": "Branch updated."}

@router.delete("/branches/{branch_id}")
async def delete_branch(branch_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_super_admin)):
    result = await db.execute(select(Branch).where(Branch.id == branch_id))
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
        
    # Delete related snapshots and alerts
    from models import SaleSnapshot, Alert
    await db.execute(delete(SaleSnapshot).where(SaleSnapshot.branch_id == branch_id))
    await db.execute(delete(Alert).where(Alert.branch_id == branch_id))
    
    await db.delete(branch)
    await db.commit()
    return {"status": "ok"}
