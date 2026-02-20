from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DashboardPeriod(str):
    # for docs only (FastAPI doesn't enforce Literal unless you want it)
    pass


class DashboardSummaryBestSellerOut(BaseModel):
    user_id: Optional[int] = None
    username: str = ""
    sales_cents: int = 0
    orders_count: int = 0
    units: int = 0


class DashboardSummaryBestPlanOut(BaseModel):
    plan_id: Optional[int] = None
    plan_title: str = ""
    plan_category: str = ""
    sales_cents: int = 0
    orders_count: int = 0
    units: int = 0


class DashboardSummaryOut(BaseModel):
    period: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

    total_sales_cents: int = 0
    total_orders: int = 0
    total_units: int = 0

    # ledger-based income/profit (driven by WalletLedger)
    admin_base_cents: int = 0
    admin_profit_cents: int = 0
    total_profit_cents: int = 0

    best_seller: DashboardSummaryBestSellerOut = Field(default_factory=DashboardSummaryBestSellerOut)
    best_plan: DashboardSummaryBestPlanOut = Field(default_factory=DashboardSummaryBestPlanOut)


class SalesByPlanRowOut(BaseModel):
    plan_id: int
    plan_title: str = ""
    plan_category: str = ""
    sales_cents: int = 0
    orders_count: int = 0
    units: int = 0


class SalesByPlanOut(BaseModel):
    period: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    items: list[SalesByPlanRowOut] = Field(default_factory=list)


class SalesBySellerRowOut(BaseModel):
    user_id: int
    username: str = ""
    sales_cents: int = 0
    orders_count: int = 0
    units: int = 0


class SalesBySellerOut(BaseModel):
    period: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    items: list[SalesBySellerRowOut] = Field(default_factory=list)


class ProfitBySellerRowOut(BaseModel):
    user_id: int
    username: str = ""
    profit_cents: int = 0


class ProfitBySellerOut(BaseModel):
    period: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    items: list[ProfitBySellerRowOut] = Field(default_factory=list)


class BalanceOverviewRowOut(BaseModel):
    user_id: int
    username: str = ""
    role: str = ""
    balance_cents: int = 0
    currency: str = "USD"
    updated_at: Optional[datetime] = None


class BalanceOverviewOut(BaseModel):
    items: list[BalanceOverviewRowOut] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0
    total: int = 0
