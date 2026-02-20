from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.coupon import Coupon
from app.models.user import User
from app.schemas.coupon_events import CouponEventOut, RecentCouponEventOut
from app.services.coupons import seller_coupon_events_for_code_bucketed, seller_recent_coupon_events_rollup

router = APIRouter(prefix="/sellers/coupons", tags=["Seller - Coupon Events"])


def _bucket_owner_to_direct_child(
    *, seller_path: str, seller_id: int, owner_id: int | None, owner_path: str | None
) -> int | None:
    if owner_id is None or owner_path is None:
        return None
    sp = str(seller_path)
    op = str(owner_path)
    if op == sp:
        return int(seller_id)
    prefix = sp + "."
    if not op.startswith(prefix):
        # outside subtree (should not happen if queries are correct)
        return int(seller_id)
    rest = op[len(prefix) :]
    first = rest.split(".", 1)[0]
    if first.startswith("u"):
        try:
            return int(first[1:])
        except Exception:
            return int(seller_id)
    return int(seller_id)


@router.get("/events/recent", response_model=list[RecentCouponEventOut])
async def list_recent_coupon_events_rollup(
    limit: int = Query(default=10, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    seller_user: User = Depends(require_seller),
):
    rows = await seller_recent_coupon_events_rollup(
        db,
        seller_user=seller_user,
        limit=int(limit),
        offset=int(offset),
    )
    return [RecentCouponEventOut(**r) for r in rows]


@router.get("/{coupon_code}/events", response_model=list[CouponEventOut])
async def list_coupon_events_bucketed(
    coupon_code: str,
    db: AsyncSession = Depends(get_db),
    seller_user: User = Depends(require_seller),
):
    # Ensure coupon exists and grab owner for bucketing
    res = await db.execute(select(Coupon.owner_user_id).where(Coupon.coupon_code == coupon_code))
    owner_id = res.scalar_one_or_none()
    owner_path = None
    if owner_id is not None:
        owner = await db.get(User, int(owner_id))
        owner_path = str(owner.path) if owner else None

    bucket_actor = _bucket_owner_to_direct_child(
        seller_path=str(seller_user.path),
        seller_id=int(seller_user.id),
        owner_id=(int(owner_id) if owner_id is not None else None),
        owner_path=owner_path,
    )

    events = await seller_coupon_events_for_code_bucketed(db, seller_user=seller_user, coupon_code=coupon_code)

    # Rewrite actor_user_id to bucket (hide grandchildren)
    out: list[CouponEventOut] = []
    for e in events:
        out.append(
            CouponEventOut(
                id=int(e.id),
                coupon_code=str(e.coupon_code),
                actor_user_id=bucket_actor,
                event_type=str(e.event_type),
                meta=e.meta or {},
                created_at=e.created_at,
            )
        )
    return out