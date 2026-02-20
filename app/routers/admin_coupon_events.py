from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.coupon import Coupon
from app.models.coupon_event import CouponEvent
from app.schemas.coupon_events import CouponEventOut, RecentCouponEventOut

router = APIRouter(prefix="/admin/coupons", tags=["Admin - Coupon Events"])


@router.get("/events/recent", response_model=list[RecentCouponEventOut])
async def list_recent_coupon_events(
    limit: int = Query(default=10, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    """
    Recent coupon events across all coupons (newest first), with Coupon.status.
    """
    stmt = (
        select(
            CouponEvent.id,
            CouponEvent.coupon_code,
            CouponEvent.actor_user_id,
            CouponEvent.event_type,
            CouponEvent.created_at,
            Coupon.status,
        )
        .select_from(CouponEvent)
        .join(Coupon, Coupon.coupon_code == CouponEvent.coupon_code)
        .order_by(CouponEvent.created_at.desc(), CouponEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )

    res = await db.execute(stmt)

    items: list[RecentCouponEventOut] = []
    for r in res.all():
        items.append(
            RecentCouponEventOut(
                id=int(r[0]),
                coupon_code=str(r[1]),
                actor_user_id=(int(r[2]) if r[2] is not None else None),
                event_type=str(r[3]),
                created_at=r[4],
                status=str(r[5]),
            )
        )

    return items


@router.get("/{coupon_code}/events", response_model=list[CouponEventOut])
async def list_coupon_events(
    coupon_code: str,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    stmt = (
        select(CouponEvent)
        .where(CouponEvent.coupon_code == coupon_code)
        .order_by(CouponEvent.created_at.asc(), CouponEvent.id.asc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()
