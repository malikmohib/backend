# app/services/seller_order_report.py
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, case, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.user import User
from app.schemas.order_report import OrderReportOut


class SellerOrderReportError(Exception):
    pass


async def get_seller_order_report_json_scoped_by_path(
    db: AsyncSession,
    *,
    bucket_user_id: int,
    bucket_username: str,
    scope_path: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    currency: Optional[str] = None,
    limit: int = 5000,
    offset: int = 0,
) -> OrderReportOut:
    """
    Seller report:
    - Includes ALL orders where buyer is in scope_path subtree (grandchildren included)
    - Returns bucket identity as the direct child (or seller self) => NO grandchild leakage
    - Uses Order + OrderItem coupon codes (so coupon purchases show up)
    """

    # Use Order.order_no if present; else fallback to Order.id
    order_no_col = getattr(Order, "order_no", Order.id).label("order_no")

    unit_price_cents = cast(
        case(
            (Order.quantity > 0, Order.total_paid_cents / Order.quantity),
            else_=0,
        ),
        Integer,
    ).label("unit_price_cents")

    # Aggregate coupon codes and keys_text from order_items
    coupon_codes_agg = func.array_agg(OrderItem.coupon_code).filter(
        OrderItem.coupon_code.isnot(None)
    ).label("coupon_codes")

    keys_text_agg = func.string_agg(OrderItem.coupon_code, "\n").filter(
        OrderItem.coupon_code.isnot(None)
    ).label("keys_text")

    q = (
        select(
            order_no_col,
            Order.created_at.label("created_at"),
            Order.plan_id.label("plan_id"),
            Plan.title.label("plan_title"),
            Plan.category.label("plan_category"),
            Order.quantity.label("quantity"),
            unit_price_cents,
            Order.total_paid_cents.label("total_paid_cents"),
            Order.currency.label("currency"),
            coupon_codes_agg,
            keys_text_agg,
        )
        .select_from(Order)
        .join(User, User.id == Order.buyer_user_id)  # only for scoping
        .join(Plan, Plan.id == Order.plan_id)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(User.path.op("<@")(scope_path))
    )

    # date_from/date_to are DATE, but created_at is datetime => compare by date()
    if date_from is not None:
        q = q.where(func.date(Order.created_at) >= date_from)
    if date_to is not None:
        q = q.where(func.date(Order.created_at) <= date_to)
    if currency:
        q = q.where(Order.currency == currency)

    # ✅ FIX: group by primary keys (required for aggregates + ORDER BY)
    q = (
        q.group_by(Order.id, Plan.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(int(limit))
        .offset(int(offset))
    )

    res = await db.execute(q)
    rows = res.mappings().all()

    items: List[Dict[str, Any]] = []
    total_amount_cents = 0

    for r in rows:
        total_paid = int(r["total_paid_cents"] or 0)
        total_amount_cents += total_paid

        coupon_codes = r["coupon_codes"] or []
        if isinstance(coupon_codes, (list, tuple)):
            coupon_codes_list = [str(x) for x in coupon_codes if x]
        else:
            coupon_codes_list = []

        keys_text = r["keys_text"] or ""
        if keys_text is None:
            keys_text = ""

        items.append(
            {
                "order_no": int(r["order_no"]),
                "created_at": r["created_at"],
                "plan_id": int(r["plan_id"]) if r["plan_id"] is not None else 0,
                "plan_title": r["plan_title"] or "",
                "plan_category": r["plan_category"] or "",
                "quantity": int(r["quantity"] or 0),
                "unit_price_cents": int(r["unit_price_cents"] or 0),
                "total_paid_cents": total_paid,
                "currency": r["currency"] or "USD",

                "coupon_codes": coupon_codes_list,
                "serials": [],  # keep for frontend compatibility
                "keys_text": keys_text,
                "serials_text": "",
            }
        )

    dt_from = (
        datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        if date_from
        else None
    )
    dt_to = (
        datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
        if date_to
        else None
    )

    return OrderReportOut(
        username=bucket_username,
        buyer_user_id=int(bucket_user_id),
        date_from=dt_from,
        date_to=dt_to,
        items=items,
        total=len(items),
    )