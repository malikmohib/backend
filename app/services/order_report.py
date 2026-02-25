# app/services/order_report.py
from __future__ import annotations

from datetime import date
from typing import Optional, List, Dict, Any

from sqlalchemy import select, and_, func, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.certificate import Certificate
from app.models.user import User
from app.schemas.order_report import OrderReportOut


class OrderReportError(Exception):
    pass


# =========================
# SELLER REPORT (KEEP AS-IS)
# =========================
async def get_order_report_json_scoped_by_path(
    db: AsyncSession,
    *,
    bucket_user_id: int,
    bucket_username: str,
    scope_path: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    currency: Optional[str] = None,
) -> OrderReportOut:
    """
    Seller version:
    - Includes ALL orders where buyer_user is in scope_path subtree (grandchildren included)
    - Returns bucket identity as the direct child (or seller self) so grandchildren are never exposed.
    """

    q = (
        select(
            OrderItem.id.label("order_item_id"),
            Order.id.label("order_id"),
            Order.created_at.label("created_at"),
            Plan.title.label("plan_title"),
            Order.total_paid_cents.label("amount_cents"),
            Order.currency.label("currency"),
            Coupon.coupon_code.label("coupon_code"),
            Certificate.serial.label("serial_value"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Plan, Plan.id == OrderItem.plan_id)
        .outerjoin(Coupon, Coupon.id == OrderItem.coupon_id)
        .outerjoin(Certificate, Certificate.order_item_id == OrderItem.id)
        .join(User, User.id == Order.buyer_user_id)
        .where(User.path.op("<@")(scope_path))
        .order_by(Order.created_at.desc(), Order.id.desc(), OrderItem.id.desc())
    )

    if date_from is not None:
        q = q.where(Order.created_at >= date_from)
    if date_to is not None:
        q = q.where(Order.created_at <= date_to)
    if currency:
        q = q.where(Order.currency == currency)

    res = await db.execute(q)
    rows = res.mappings().all()

    items: List[Dict[str, Any]] = []
    total_amount_cents = 0

    for r in rows:
        amt = int(r["amount_cents"] or 0)
        total_amount_cents += amt
        items.append(
            {
                "order_item_id": int(r["order_item_id"]),
                "order_id": int(r["order_id"]),
                "created_at": r["created_at"],
                "plan_title": r["plan_title"],
                "amount_cents": amt,
                "currency": r["currency"],
                "coupon_code": r["coupon_code"],
                "serial_value": r["serial_value"],
            }
        )

    resolved_currency = currency or (rows[0]["currency"] if rows else "USD")

    return OrderReportOut(
        buyer_user_id=bucket_user_id,
        username=bucket_username,
        total_amount_cents=total_amount_cents,
        currency=resolved_currency,
        items=items,
    )


async def get_order_report_json(
    db: AsyncSession,
    *,
    buyer_user_id: int,
    username: str,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    currency: Optional[str] = None,
    limit: int = 5000,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Admin version (used by /admin/reports/orders):
    - Returns JSON dict that matches OrderReportOut EXACTLY
    - Uses orders table for core fields (same as seller report)
    - Aggregates coupon_codes + serials from order_items
    - Supports filters: buyer_user_id, plan_id, status, date_from, date_to, currency, limit, offset
    """

    from sqlalchemy import select, func, distinct
    from app.models.order import Order
    from app.models.order_item import OrderItem
    from app.models.plan import Plan

    # Aggregate arrays from order_items
    coupon_codes_agg = func.array_agg(distinct(OrderItem.coupon_code)).label("coupon_codes")
    serials_agg = func.array_agg(distinct(OrderItem.serial)).label("serials")

    q = (
        select(
            Order.id.label("order_no"),                 # ✅ seller report uses Order.id as order_no
            Order.created_at.label("created_at"),
            Order.plan_id.label("plan_id"),
            Plan.title.label("plan_title"),
            Plan.category.label("plan_category"),
            Order.quantity.label("quantity"),
            Order.unit_price_cents.label("unit_price_cents"),
            Order.total_paid_cents.label("total_paid_cents"),
            Order.currency.label("currency"),
            coupon_codes_agg,
            serials_agg,
        )
        .select_from(Order)
        .join(Plan, Plan.id == Order.plan_id)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.buyer_user_id == buyer_user_id)
        .group_by(
            Order.id,
            Order.created_at,
            Order.plan_id,
            Plan.title,
            Plan.category,
            Order.quantity,
            Order.unit_price_cents,
            Order.total_paid_cents,
            Order.currency,
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(int(limit))
        .offset(int(offset))
    )

    # Filters
    if plan_id is not None:
        q = q.where(Order.plan_id == plan_id)
    if status:
        q = q.where(Order.status == status)
    if date_from is not None:
        q = q.where(Order.created_at >= date_from)
    if date_to is not None:
        q = q.where(Order.created_at <= date_to)
    if currency:
        q = q.where(Order.currency == currency)

    res = await db.execute(q)
    rows = res.mappings().all()

    items: List[Dict[str, Any]] = []

    for r in rows:
        coupon_codes = r["coupon_codes"] or []
        # array_agg on outerjoin can produce [None] — clean it
        coupon_codes = [c for c in coupon_codes if c]

        serials = r["serials"] or []
        serials = [s for s in serials if s]

        items.append(
            {
                "order_no": int(r["order_no"]),
                "created_at": r["created_at"],
                "plan_id": int(r["plan_id"]) if r["plan_id"] is not None else 0,
                "plan_title": r["plan_title"] or "",
                "plan_category": r["plan_category"] or "",
                "quantity": int(r["quantity"] or 0),
                "unit_price_cents": int(r["unit_price_cents"] or 0),
                "total_paid_cents": int(r["total_paid_cents"] or 0),
                "currency": r["currency"] or "USD",
                "coupon_codes": coupon_codes,
                "serials": serials,
                "keys_text": "\n".join(coupon_codes) if coupon_codes else "",
                "serials_text": "\n".join(serials) if serials else "",
            }
        )

    # ✅ Must match schema: total is required int.
    # Seller report uses total=len(items), so keep consistent.
    return {
        "username": username or "",
        "buyer_user_id": int(buyer_user_id),
        "date_from": date_from,
        "date_to": date_to,
        "plan_id": plan_id,
        "status": status,
        "items": items,
        "total": len(items),
    }