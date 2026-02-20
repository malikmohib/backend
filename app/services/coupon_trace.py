from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certificate import Certificate
from app.models.coupon import Coupon
from app.models.coupon_event import CouponEvent
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.user import User


class CouponTraceError(Exception):
    pass


async def _username_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    user_ids = [int(x) for x in set(user_ids) if x is not None]
    if not user_ids:
        return {}
    res = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
    return {int(r[0]): (r[1] or "") for r in res.all()}


async def trace_coupon(
    db: AsyncSession,
    *,
    coupon_code: str,
    include_events: bool = True,
) -> dict:
    # coupon + plan (+ optional certificate)
    stmt = (
        select(Coupon, Plan, Certificate)
        .join(Plan, Plan.id == Coupon.plan_id)
        .outerjoin(Certificate, Certificate.coupon_code == Coupon.coupon_code)
        .where(Coupon.coupon_code == coupon_code)
        .limit(1)
    )
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise CouponTraceError("Coupon not found.")

    c: Coupon = row[0]
    p: Plan = row[1]
    cert: Certificate | None = row[2]

    # order link (optional)
    order_no = None
    tx_id = None
    link_stmt = (
        select(Order.order_no, Order.tx_id)
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.coupon_code == coupon_code)
        .limit(1)
    )
    link_res = await db.execute(link_stmt)
    link = link_res.first()
    if link:
        order_no = int(link[0]) if link[0] is not None else None
        tx_id = str(link[1]) if link[1] else None

    # events
    events_out: list[dict] = []
    event_rows: list[CouponEvent] = []
    if include_events:
        ev_stmt = (
            select(CouponEvent)
            .where(CouponEvent.coupon_code == coupon_code)
            .order_by(CouponEvent.created_at.asc(), CouponEvent.id.asc())
        )
        ev_res = await db.execute(ev_stmt)
        event_rows = ev_res.scalars().all()

    # usernames
    user_ids: list[int] = []
    for v in [c.created_by_user_id, c.owner_user_id, c.reserved_by_user_id, c.used_by_user_id]:
        if v is not None:
            user_ids.append(int(v))
    for ev in event_rows:
        if ev.actor_user_id is not None:
            user_ids.append(int(ev.actor_user_id))

    uname = await _username_map(db, user_ids)

    if include_events:
        for ev in event_rows:
            actor_username = ""
            if ev.actor_user_id is not None:
                actor_username = uname.get(int(ev.actor_user_id), "")
            events_out.append(
                {
                    "id": int(ev.id),
                    "created_at": ev.created_at,
                    "event_type": ev.event_type,
                    "actor_user_id": int(ev.actor_user_id) if ev.actor_user_id is not None else None,
                    "actor_username": actor_username,
                    "meta": ev.meta or {},
                }
            )

    def _u(uid):
        if uid is None:
            return ("", None)
        return (uname.get(int(uid), ""), int(uid))

    created_by_username, _ = _u(c.created_by_user_id)
    owner_username, _ = _u(c.owner_user_id)
    reserved_by_username, _ = _u(c.reserved_by_user_id)
    used_by_username, _ = _u(c.used_by_user_id)

    return {
        "coupon_code": c.coupon_code,
        "status": c.status,
        "plan_id": int(c.plan_id),
        "plan_title": getattr(p, "title", "") or "",
        "plan_category": getattr(p, "category", "") or "",
        "created_at": c.created_at,
        "created_by_user_id": int(c.created_by_user_id) if c.created_by_user_id is not None else None,
        "created_by_username": created_by_username,
        "owner_user_id": int(c.owner_user_id) if c.owner_user_id is not None else None,
        "owner_username": owner_username,
        "reserved_by_user_id": int(c.reserved_by_user_id) if c.reserved_by_user_id is not None else None,
        "reserved_by_username": reserved_by_username,
        "reserved_udid": c.reserved_udid,
        "reserved_at": c.reserved_at,
        "used_by_user_id": int(c.used_by_user_id) if c.used_by_user_id is not None else None,
        "used_by_username": used_by_username,
        "used_udid": c.used_udid,
        "used_at": c.used_at,
        "provider_req_id": c.provider_req_id,
        "notes": c.notes,
        "last_failure_reason": c.last_failure_reason,
        "last_failure_step": c.last_failure_step,
        "last_failed_at": c.last_failed_at,
        "order_no": order_no,
        "tx_id": tx_id,
        # certificate linkage (blank/None when missing)
        "certificate_telegram_id": (getattr(cert, "telegram_id", "") or "") if cert else "",
        "certificate_serial": (getattr(cert, "serial", "") or "") if cert else "",
        "certificate_udid": (getattr(cert, "udid", "") or "") if cert else "",
        "certificate_created_at": getattr(cert, "created_at", None) if cert else None,
        "events": events_out,
    }
