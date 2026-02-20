from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.dashboard import (
    BalanceOverviewOut,
    DashboardSummaryOut,
    ProfitBySellerOut,
    SalesByPlanOut,
    SalesBySellerOut,
)
from app.services.dashboard import (
    balances_overview,
    dashboard_summary_seller_direct,
    profit_by_seller,
    sales_by_plan,
    sales_by_seller,
    _direct_scope_user_ids,
)


router = APIRouter(prefix="/sellers/dashboard", tags=["Seller Dashboard"])


@router.get("/summary", response_model=DashboardSummaryOut)
async def seller_dashboard_summary(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummaryOut:
    data = await dashboard_summary_seller_direct(
        db,
        current_user_id=int(current_user.id),
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return DashboardSummaryOut(**data)


@router.get("/sales-by-plan", response_model=SalesByPlanOut)
async def seller_sales_by_plan(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SalesByPlanOut:
    scope_ids = await _direct_scope_user_ids(db, current_user_id=int(current_user.id))
    data = await sales_by_plan(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=scope_ids, limit=limit)
    return SalesByPlanOut(**data)


@router.get("/sales-by-seller", response_model=SalesBySellerOut)
async def seller_sales_by_seller(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SalesBySellerOut:
    scope_ids = await _direct_scope_user_ids(db, current_user_id=int(current_user.id))
    data = await sales_by_seller(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=scope_ids, limit=limit)
    return SalesBySellerOut(**data)


@router.get("/profit-by-seller", response_model=ProfitBySellerOut)
async def seller_profit_by_seller(
    period: str = Query(default="today"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfitBySellerOut:
    scope_ids = await _direct_scope_user_ids(db, current_user_id=int(current_user.id))
    data = await profit_by_seller(db, period=period, date_from=date_from, date_to=date_to, user_ids=scope_ids, limit=limit)
    return ProfitBySellerOut(**data)


@router.get("/balances", response_model=BalanceOverviewOut)
async def seller_balances_overview(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BalanceOverviewOut:
    scope_ids = await _direct_scope_user_ids(db, current_user_id=int(current_user.id))
    data = await balances_overview(db, user_ids=scope_ids, limit=limit, offset=offset)
    return BalanceOverviewOut(**data)
