from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.user import User


class OrderReportError(Exception):
    pass


async def _get_user_by_username(db: AsyncSession, username: str) -> User:
    res = await db.execute(select(User).where(User.username == username))
    u = res.scalar_one_or_none()
    if u is None:
        raise OrderReportError("User not found.")
    return u


async def get_order_report_json(
    db: AsyncSession,
    *,
    buyer_user_id: int,
    username: str,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 5000,
    offset: int = 0,
) -> dict:
    filters = [Order.buyer_user_id == buyer_user_id]

    if plan_id is not None:
        filters.append(Order.plan_id == plan_id)
    if status is not None:
        filters.append(Order.status == status)
    if date_from is not None:
        filters.append(Order.created_at >= date_from)
    if date_to is not None:
        filters.append(Order.created_at <= date_to)

    total_stmt = select(func.count()).select_from(Order).where(*filters)
    total_res = await db.execute(total_stmt)
    total = int(total_res.scalar() or 0)

    # Orders newest-first (dashboard)
    orders_stmt = (
        select(
            Order.id,
            Order.order_no,
            Order.created_at,
            Order.plan_id,
            Order.quantity,
            Order.unit_price_cents,
            Order.total_paid_cents,
            Order.currency,
            Order.status,
            Plan.title.label("plan_title"),
            Plan.category.label("plan_category"),
        )
        .join(Plan, Plan.id == Order.plan_id)
        .where(*filters)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
        .offset(offset)
    )

    res = await db.execute(orders_stmt)
    orders = res.mappings().all()

    if not orders:
        return {
            "username": username,
            "buyer_user_id": int(buyer_user_id),
            "date_from": date_from,
            "date_to": date_to,
            "plan_id": plan_id,
            "status": status,
            "items": [],
            "total": total,
        }

    order_ids = [int(o["id"]) for o in orders]

    items_stmt = (
        select(
            OrderItem.order_id,
            OrderItem.coupon_code,
            OrderItem.serial,
        )
        .where(OrderItem.order_id.in_(order_ids))
        .order_by(OrderItem.id.asc())
    )
    items_res = await db.execute(items_stmt)
    item_rows = items_res.all()

    by_order: dict[int, dict[str, list[str]]] = {}
    for oid, code, serial in item_rows:
        oid_int = int(oid)
        if oid_int not in by_order:
            by_order[oid_int] = {"codes": [], "serials": []}
        by_order[oid_int]["codes"].append(code)
        by_order[oid_int]["serials"].append(serial or "")

    out_items = []
    for o in orders:
        oid = int(o["id"])
        codes = by_order.get(oid, {}).get("codes", [])
        serials = by_order.get(oid, {}).get("serials", [])

        keys_text = "\n".join([c for c in codes if c])
        serials_text = "\n".join([s for s in serials if s])

        out_items.append(
            {
                "order_no": int(o["order_no"]),
                "created_at": o["created_at"],
                "plan_id": int(o["plan_id"]),
                "plan_title": o["plan_title"] or "",
                "plan_category": o["plan_category"] or "",
                "quantity": int(o["quantity"]),
                "unit_price_cents": int(o["unit_price_cents"]),
                "total_paid_cents": int(o["total_paid_cents"]),
                "currency": o["currency"],
                "coupon_codes": codes,
                "serials": serials,
                "keys_text": keys_text,
                "serials_text": serials_text,
            }
        )

    return {
        "username": username,
        "buyer_user_id": int(buyer_user_id),
        "date_from": date_from,
        "date_to": date_to,
        "plan_id": plan_id,
        "status": status,
        "items": out_items,
        "total": total,
    }
