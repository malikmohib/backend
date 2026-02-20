from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.user import User


class OrdersError(Exception):
    pass


async def _get_username_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    res = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
    rows = res.all()
    return {int(r[0]): (r[1] or "") for r in rows}


async def _get_plan_map(db: AsyncSession, plan_ids: list[int]) -> dict[int, Plan]:
    if not plan_ids:
        return {}
    res = await db.execute(select(Plan).where(Plan.id.in_(plan_ids)))
    plans = res.scalars().all()
    return {int(p.id): p for p in plans}


async def list_orders(
    db: AsyncSession,
    *,
    buyer_user_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    filters = []

    if buyer_user_id is not None:
        filters.append(Order.buyer_user_id == buyer_user_id)
    if plan_id is not None:
        filters.append(Order.plan_id == plan_id)
    if status is not None:
        filters.append(Order.status == status)
    if date_from is not None:
        filters.append(Order.created_at >= date_from)
    if date_to is not None:
        filters.append(Order.created_at <= date_to)

    where_clause = and_(*filters) if filters else None

    # total
    total_stmt = select(func.count()).select_from(Order)
    if where_clause is not None:
        total_stmt = total_stmt.where(where_clause)

    total_res = await db.execute(total_stmt)
    total = int(total_res.scalar_one())

    # orders list
    stmt = (
        select(Order)
        .order_by(Order.created_at.desc(), Order.order_no.desc())
        .limit(limit)
        .offset(offset)
    )
    if where_clause is not None:
        stmt = stmt.where(where_clause)

    res = await db.execute(stmt)
    orders = res.scalars().all()

    order_ids = [int(o.id) for o in orders]
    buyer_ids = list({int(o.buyer_user_id) for o in orders})
    plan_ids = list({int(o.plan_id) for o in orders})

    username_map = await _get_username_map(db, buyer_ids)
    plan_map = await _get_plan_map(db, plan_ids)

    # items for all orders
    items_map: dict[int, list[OrderItem]] = {}
    if order_ids:
        items_stmt = (
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.id.asc())
        )
        items_res = await db.execute(items_stmt)
        for it in items_res.scalars().all():
            items_map.setdefault(int(it.order_id), []).append(it)

    out_items = []
    for o in orders:
        plan = plan_map.get(int(o.plan_id))

        its = items_map.get(int(o.id), [])
        coupon_codes = [it.coupon_code for it in its]
        keys_text = "\n".join(coupon_codes)

        serial = ""
        for it in its:
            if it.serial:
                serial = it.serial
                break

        out_items.append(
            {
                "order_no": int(o.order_no),
                "tx_id": str(o.tx_id),
                "buyer_user_id": int(o.buyer_user_id),
                "purchaser_username": username_map.get(int(o.buyer_user_id), ""),
                "plan_id": int(o.plan_id),
                "plan_title": (getattr(plan, "title", "") or "") if plan else "",
                "plan_category": (getattr(plan, "category", "") or "") if plan else "",
                "quantity": int(o.quantity),
                "unit_price_cents": int(o.unit_price_cents),
                "total_paid_cents": int(o.total_paid_cents),
                "currency": o.currency,
                "status": o.status,
                "created_at": o.created_at,
                "coupon_codes": coupon_codes,
                "keys_text": keys_text,
                "serial": serial,
            }
        )

    return {"items": out_items, "limit": limit, "offset": offset, "total": total}


async def get_order_by_order_no(
    db: AsyncSession,
    *,
    order_no: int,
) -> dict:
    stmt = select(Order).where(Order.order_no == order_no).limit(1)
    res = await db.execute(stmt)
    o = res.scalar_one_or_none()
    if not o:
        raise OrdersError("Order not found.")

    username_map = await _get_username_map(db, [int(o.buyer_user_id)])
    plan_map = await _get_plan_map(db, [int(o.plan_id)])
    plan = plan_map.get(int(o.plan_id))

    items_stmt = (
        select(OrderItem)
        .where(OrderItem.order_id == o.id)
        .order_by(OrderItem.id.asc())
    )
    items_res = await db.execute(items_stmt)
    its = items_res.scalars().all()

    coupon_codes = [it.coupon_code for it in its]
    keys_text = "\n".join(coupon_codes)

    serial = ""
    for it in its:
        if it.serial:
            serial = it.serial
            break

    return {
        "order_no": int(o.order_no),
        "tx_id": str(o.tx_id),
        "buyer_user_id": int(o.buyer_user_id),
        "purchaser_username": username_map.get(int(o.buyer_user_id), ""),
        "plan_id": int(o.plan_id),
        "plan_title": (getattr(plan, "title", "") or "") if plan else "",
        "plan_category": (getattr(plan, "category", "") or "") if plan else "",
        "quantity": int(o.quantity),
        "unit_price_cents": int(o.unit_price_cents),
        "total_paid_cents": int(o.total_paid_cents),
        "currency": o.currency,
        "status": o.status,
        "created_at": o.created_at,
        "coupon_codes": coupon_codes,
        "keys_text": keys_text,
        "serial": serial,
    }
