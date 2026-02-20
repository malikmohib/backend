from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.coupon import Coupon
from app.models.user import User
from app.schemas.coupon_trace import CouponTraceOut
from app.services.coupon_trace import CouponTraceError, trace_coupon


router = APIRouter(prefix="/sellers/coupon-trace", tags=["Seller Coupon Trace"])


@router.get("/{coupon_code}", response_model=CouponTraceOut)
async def seller_trace_coupon(
    coupon_code: str,
    include_events: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CouponTraceOut:
    # Access rule:
    # - seller can trace coupons they own
    # - OR coupons owned by their direct child (owner.parent_id == current_user.id)
    # Return 404 if not allowed to avoid leaking existence.
    res = await db.execute(
        select(Coupon.id)
        .select_from(Coupon)
        .join(User, User.id == Coupon.owner_user_id)
        .where(
            Coupon.coupon_code == coupon_code,
            (Coupon.owner_user_id == current_user.id) | (User.parent_id == current_user.id),
        )
        .limit(1)
    )
    allowed = res.first()
    if not allowed:
        raise HTTPException(status_code=404, detail="Coupon not found.")

    try:
        data = await trace_coupon(db, coupon_code=coupon_code, include_events=include_events)
        return CouponTraceOut(**data)
    except CouponTraceError as e:
        raise HTTPException(status_code=404, detail=str(e))
