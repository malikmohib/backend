from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.user import User
from app.schemas.coupons import AdminCouponResponse, SellerCouponGenerateRequest
from app.services.coupons import seller_generate_coupons, seller_list_coupons

router = APIRouter(prefix="/sellers/coupons", tags=["Seller - Coupons"])


@router.post("", response_model=list[AdminCouponResponse])
async def generate_coupons(
    body: SellerCouponGenerateRequest,
    db: AsyncSession = Depends(get_db),
    seller_user: User = Depends(require_seller),
):
    return await seller_generate_coupons(
        db,
        plan_id=body.plan_id,
        count=body.count,
        seller_user_id=int(seller_user.id),
        owner_user_id=body.owner_user_id,
        notes=body.notes,
    )


@router.get("", response_model=list[AdminCouponResponse])
async def list_coupons(
    status: str | None = Query(default=None),
    plan_id: int | None = Query(default=None),
    owner_user_id: int | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    seller_user: User = Depends(require_seller),
):
    return await seller_list_coupons(
        db,
        seller_user_id=int(seller_user.id),
        status=status,
        plan_id=plan_id,
        owner_user_id=owner_user_id,
        limit=int(limit),
        offset=int(offset),
    )