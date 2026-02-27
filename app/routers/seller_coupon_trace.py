# app/routers/seller_coupon_trace.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.user import User
from app.models.coupon import Coupon  # make sure your coupon model is here

# If you have a coupon events model, import it.
# If not, you can remove the events section below.
try:
    from app.models.coupon_event import CouponEvent  # type: ignore
except Exception:
    CouponEvent = None  # type: ignore


router = APIRouter(prefix="/sellers", tags=["seller-coupon-trace"])


def _getattr_any(obj, names: list[str]):
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


@router.get("/coupon-trace/{coupon_code}")
async def seller_trace_coupon(
    coupon_code: str,
    include_events: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
):
    """
    Seller coupon trace:
    - Seller can ONLY trace coupons owned by seller OR anyone in seller subtree.
    - Coupon lookup by coupon_code (not Coupon.id).
    """

    # 1) Load coupon by coupon_code
    res = await db.execute(
        select(Coupon).where(Coupon.coupon_code == str(coupon_code))
    )
    coupon = res.scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    owner_user_id = int(getattr(coupon, "owner_user_id", 0) or 0)
    if owner_user_id <= 0:
        # If your schema allows null owner, fallback to created_by_user_id for scoping
        owner_user_id = int(getattr(coupon, "created_by_user_id", 0) or 0)

    if owner_user_id <= 0:
        raise HTTPException(status_code=400, detail="Coupon missing owner_user_id")

    # 2) Enforce subtree scope: owner must be in seller subtree (including self)
    # users.path is ltree, so we check: owner.path <@ seller.path
    owner_res = await db.execute(select(User).where(User.id == owner_user_id))
    owner = owner_res.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=400, detail="Coupon owner user not found")

    seller_path = str(current_seller.path)
    owner_path = str(owner.path)

    # owner must be inside seller subtree
    # "owner_path <@ seller_path"
    # Using SQL to be correct with ltree operator
    scope_check = await db.execute(
        select(User.id)
        .where(User.id == int(owner_user_id))
        .where(User.path.op("<@")(seller_path))
    )
    if scope_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Forbidden: coupon not in your subtree")

    # 3) Base response
    out = {
        "coupon_code": getattr(coupon, "coupon_code", None),
        "plan_id": int(getattr(coupon, "plan_id", 0) or 0),
        "status": getattr(coupon, "status", None),
        "created_at": getattr(coupon, "created_at", None),
        "created_by_user_id": int(getattr(coupon, "created_by_user_id", 0) or 0),
        "owner_user_id": int(getattr(coupon, "owner_user_id", 0) or 0),
        "owner_username": owner.username,
        "owner_path": owner_path,
        "events": [],
    }

    # 4) Optional events
    if include_events and CouponEvent is not None:
        # Try common schemas:
        # CouponEvent has coupon_code OR coupon_id; use what exists.
        ev_coupon_code_col = _getattr_any(CouponEvent, ["coupon_code", "code"])
        ev_created_at_col = _getattr_any(CouponEvent, ["created_at", "at", "timestamp"])
        ev_kind_col = _getattr_any(CouponEvent, ["event_kind", "kind", "action", "type"])
        ev_note_col = _getattr_any(CouponEvent, ["note", "message", "detail"])
        ev_user_id_col = _getattr_any(CouponEvent, ["user_id", "actor_user_id", "by_user_id"])

        if ev_coupon_code_col is not None:
            q = select(CouponEvent).where(ev_coupon_code_col == str(coupon_code))
            if ev_created_at_col is not None:
                q = q.order_by(ev_created_at_col.asc())
            ev_res = await db.execute(q)
            ev_rows = ev_res.scalars().all()

            events_out = []
            for ev in ev_rows:
                events_out.append(
                    {
                        "created_at": getattr(ev, ev_created_at_col.key) if ev_created_at_col is not None else getattr(ev, "created_at", None),
                        "kind": getattr(ev, ev_kind_col.key) if ev_kind_col is not None else None,
                        "note": getattr(ev, ev_note_col.key) if ev_note_col is not None else None,
                        "user_id": int(getattr(ev, ev_user_id_col.key) or 0) if ev_user_id_col is not None else 0,
                    }
                )

            out["events"] = events_out

    return out