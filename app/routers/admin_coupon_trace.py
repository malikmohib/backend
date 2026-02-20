from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.schemas.coupon_trace import CouponTraceOut
from app.services.coupon_trace import trace_coupon, CouponTraceError


router = APIRouter(prefix="/admin/coupon-trace", tags=["Admin Coupon Trace"])


@router.get("/{coupon_code}", response_model=CouponTraceOut)
async def admin_trace_coupon(
    coupon_code: str,
    include_events: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> CouponTraceOut:
    try:
        data = await trace_coupon(db, coupon_code=coupon_code, include_events=include_events)
        return CouponTraceOut(**data)
    except CouponTraceError as e:
        raise HTTPException(status_code=404, detail=str(e))
