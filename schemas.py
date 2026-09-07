from datetime import datetime
from pydantic import BaseModel


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_superadmin: bool = False

class FCMTokenRequest(BaseModel):
    fcm_token: str


# ── Sync payload (Desktop → API) ──────────────────────────────────────────────

class SyncPayload(BaseModel):
    branch_name:      str
    api_key:          str | None = None

    day_id:           int

    gross_total:      float
    disc_value:       float
    disc_lines_value: float
    net_total:        float
    visa_total:       float
    
    cash_total:       float = 0.0
    wallet_total:     float = 0.0
    insta_total:      float = 0.0
    hos_total:        float = 0.0
    credit_total:     float = 0.0
    visa_tip_total:   float = 0.0
    tax_total:        float = 0.0
    expenses_total:   float = 0.0
    void_total:       float = 0.0
    
    takeaway_count:   int
    takeaway_total:   float
    delivery_count:   int
    delivery_total:   float
    dlv_service_total: float

    order_count:      int
    business_date:    str
    
    metrics_json:     dict | None = None


class SyncResponse(BaseModel):
    status:  str
    message: str


class InvoiceItemPayload(BaseModel):
    name: str
    qty: float
    price: float
    total: float

class AlertPayload(BaseModel):
    ih_serial: str | int
    ih_code: str
    order_date: str
    disc_perc: float
    total: float = 0.0
    disc_val: float = 0.0
    net_val: float = 0.0
    is_open: bool = True
    items: list[InvoiceItemPayload] = []

class SyncAlertsPayload(BaseModel):
    branch_name: str
    api_key: str | None = None
    alerts: list[AlertPayload]


# ── Dashboard (API → Mobile) ──────────────────────────────────────────────────

class BranchSummary(BaseModel):
    branch_name:      str
    day_id:           int | None = None
    business_date:    str | None = None
    gross_total:      float
    disc_value:       float
    disc_lines_value: float
    net_total:        float
    visa_total:       float
    
    cash_total:       float = 0.0
    wallet_total:     float = 0.0
    insta_total:      float = 0.0
    hos_total:        float = 0.0
    credit_total:     float = 0.0
    visa_tip_total:   float = 0.0
    tax_total:        float = 0.0
    expenses_total:   float = 0.0
    void_total:       float = 0.0
    
    takeaway_count:   int
    takeaway_total:   float
    delivery_count:   int
    delivery_total:   float
    dlv_service_total: float

    order_count:      int
    avg_order_value:  float
    last_sync:        datetime | None
    is_online:        bool
    
    metrics:          dict | None = None
    trend_perc:       float | None = None


class DashboardResponse(BaseModel):
    grand_gross_total:      float
    grand_disc:             float
    grand_disc_lines:       float
    grand_net_total:        float
    grand_visa_total:       float
    
    grand_cash_total:       float = 0.0
    grand_wallet_total:     float = 0.0
    grand_insta_total:      float = 0.0
    grand_hos_total:        float = 0.0
    grand_credit_total:     float = 0.0
    grand_visa_tip_total:   float = 0.0
    grand_tax_total:        float = 0.0
    grand_expenses_total:   float = 0.0
    grand_void_total:       float = 0.0
    
    grand_takeaway_count:   int
    grand_takeaway_total:   float
    grand_delivery_count:   int
    grand_delivery_total:   float
    grand_dlv_service_total: float

    total_orders:           int
    branches:               list[BranchSummary]
    business_date:          str
    updated_at:             datetime
    
    grand_metrics:          dict | None = None
    grand_trend_perc:       float | None = None


# ── History Models ────────────────────────────────────────────────────────────

class HistoryBranchBreakdown(BaseModel):
    branch_name: str
    net_total: float
    visa_total: float
    
    cash_total: float = 0.0
    wallet_total: float = 0.0
    insta_total: float = 0.0
    hos_total: float = 0.0
    credit_total: float = 0.0
    visa_tip_total: float = 0.0
    tax_total: float = 0.0
    expenses_total: float = 0.0
    void_total: float = 0.0
    
    takeaway_total: float
    delivery_total: float
    dlv_service_total: float
    order_count: int
    metrics: dict | None = None

class HistoryDaySummary(BaseModel):
    business_date: str
    net_total: float
    visa_total: float
    
    cash_total: float = 0.0
    wallet_total: float = 0.0
    insta_total: float = 0.0
    hos_total: float = 0.0
    credit_total: float = 0.0
    visa_tip_total: float = 0.0
    tax_total: float = 0.0
    expenses_total: float = 0.0
    void_total: float = 0.0
    
    takeaway_total: float
    delivery_total: float
    dlv_service_total: float
    total_orders: int
    branches: list[HistoryBranchBreakdown]
    metrics: dict | None = None

class HistoryResponse(BaseModel):
    month: str
    days: list[HistoryDaySummary]


# ── Alerts & Settings Models ──────────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: int
    branch_name: str
    ih_serial: str | None
    ih_code: str
    order_date: str
    disc_perc: float
    is_read: bool
    items: list[InvoiceItemPayload] | None = None
    created_at: datetime

class BranchSetting(BaseModel):
    id: int
    name: str
    max_disc_perc: float
    is_active: bool

class BranchSettingUpdate(BaseModel):
    max_disc_perc: float

