from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.schemas.dashboard import (
    BalanceOverviewOut,
    DashboardSummaryOut,
    ProfitBySellerOut,
    SalesByPlanOut,
    SalesBySellerOut,
)
from app.services.dashboard import (
    DashboardError,
    balances_overview,
    dashboard_summary_admin,
    profit_by_seller,
    sales_by_plan,
    sales_by_seller,
)


router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard"])


@router.get("/summary", response_model=DashboardSummaryOut)
async def admin_dashboard_summary(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> DashboardSummaryOut:
    try:
        data = await dashboard_summary_admin(db, period=period, date_from=date_from, date_to=date_to)
        return DashboardSummaryOut(**data)
    except DashboardError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sales-by-plan", response_model=SalesByPlanOut)
async def admin_sales_by_plan(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> SalesByPlanOut:
    data = await sales_by_plan(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=None, limit=limit)
    return SalesByPlanOut(**data)


@router.get("/sales-by-seller", response_model=SalesBySellerOut)
async def admin_sales_by_seller(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> SalesBySellerOut:
    data = await sales_by_seller(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=None, limit=limit)
    return SalesBySellerOut(**data)


@router.get("/profit-by-seller", response_model=ProfitBySellerOut)
async def admin_profit_by_seller(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ProfitBySellerOut:
    data = await profit_by_seller(db, period=period, date_from=date_from, date_to=date_to, user_ids=None, limit=limit)
    return ProfitBySellerOut(**data)


@router.get("/balances", response_model=BalanceOverviewOut)
async def admin_balances_overview(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> BalanceOverviewOut:
    data = await balances_overview(db, user_ids=None, limit=limit, offset=offset)
    return BalanceOverviewOut(**data)
