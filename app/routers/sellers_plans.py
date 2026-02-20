from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.plan import Plan
from app.models.seller_plan_price import SellerPlanPrice
from app.models.user import User
from app.schemas.plans import PlanOut

router = APIRouter(prefix="/sellers/plans", tags=["Seller - Plans"])


@router.get("/available", response_model=list[PlanOut])
async def get_available_plans(
    db: AsyncSession = Depends(get_db),
    seller_user: User = Depends(require_seller),
):
    """
    Seller can only see plans that are assigned to them via seller_plan_prices.
    If no plans assigned => empty list.
    """
    stmt = (
        select(Plan)
        .join(SellerPlanPrice, SellerPlanPrice.plan_id == Plan.id)
        .where(SellerPlanPrice.seller_id == int(seller_user.id))
        .where(Plan.is_active.is_(True))
        .order_by(Plan.category.asc(), Plan.title.asc())
    )

    res = await db.execute(stmt)
    return res.scalars().all()