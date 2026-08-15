from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, func, BigInteger, Index, JSON, Boolean, Date, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class Company(Base):
    """Tenant company."""
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    subscription_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_remind: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    branches: Mapped[list["Branch"]] = relationship(back_populates="company", cascade="all, delete-orphan")


user_branches = Table(
    "user_branches",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", Integer, ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    """Single owner user for mobile login."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    fcm_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    company: Mapped["Company | None"] = relationship(back_populates="users")
    branches: Mapped[list["Branch"]] = relationship(secondary=user_branches, back_populates="users")

    @property
    def branch_ids(self) -> list[int]:
        return [b.id for b in self.branches]


class Branch(Base):
    """Registered branch (auto-created on first sync)."""
    __tablename__ = "branches"
    __table_args__ = (
        Index("ix_branch_name_company", "name", "company_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    max_disc_perc: Mapped[float] = mapped_column(Float, nullable=False, default=100.0, comment="أقصى نسبة خصم مسموحة")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="branches")
    users: Mapped[list["User"]] = relationship(secondary=user_branches, back_populates="branches")

    snapshots: Mapped[list["SaleSnapshot"]] = relationship(
        back_populates="branch", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="branch", cascade="all, delete-orphan"
    )


class SaleSnapshot(Base):
    """
    Sales snapshot pushed by a branch desktop agent.
    Stores financial aggregates from Invoice_header.
    """
    __tablename__ = "sale_snapshots"
    __table_args__ = (
        Index("ix_snapshot_branch_date", "branch_id", "business_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    day_id: Mapped[int] = mapped_column(Integer, nullable=False)

    gross_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disc_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disc_lines_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    visa_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    
    # New breakdown fields
    takeaway_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    takeaway_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dlv_service_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    business_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD

    branch: Mapped["Branch"] = relationship(back_populates="snapshots")


class Alert(Base):
    """
    High discount alert recorded when an invoice exceeds the branch max_disc_perc.
    """
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_branch_created", "branch_id", "created_at"),
        Index("ix_alert_ih_serial", "ih_serial"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    ih_serial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ih_code: Mapped[str] = mapped_column(String(50), nullable=False)
    order_date: Mapped[str] = mapped_column(String(30), nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disc_val: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disc_perc: Mapped[float] = mapped_column(Float, nullable=False)
    net_val: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    
    invoice_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    branch: Mapped["Branch"] = relationship(back_populates="alerts")
