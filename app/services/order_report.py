# app/services/order_report.py
from __future__ import annotations

from datetime import date
from typing import Optional, List, Dict, Any

from sqlalchemy import select
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
            # Coupon code (your real column name)
            Coupon.coupon_code.label("coupon_code"),
            # Serial value (your real column name)
            Certificate.serial.label("serial_value"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Plan, Plan.id == OrderItem.plan_id)

        # Coupon is optional
        .outerjoin(Coupon, Coupon.id == OrderItem.coupon_id)

        # Certificate is optional; in your schema it belongs to order_item via order_item_id
        .outerjoin(Certificate, Certificate.order_item_id == OrderItem.id)

        # Scope by buyer's user.path subtree (grandchildren included)
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
                "coupon_code": r["coupon_code"],     # Coupon.coupon_code
                "serial_value": r["serial_value"],   # Certificate.serial
            }
        )

    resolved_currency = currency or (rows[0]["currency"] if rows else "USD")

    return OrderReportOut(
        buyer_user_id=bucket_user_id,     # ✅ bucket to direct child (or seller self)
        username=bucket_username,         # ✅ never expose grandchildren
        total_amount_cents=total_amount_cents,
        currency=resolved_currency,
        items=items,
    )
async def get_order_report_json(
    db: AsyncSession,
    *,
    buyer_user_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    currency: Optional[str] = None,
) -> OrderReportOut:
    """
    Admin version:
    - Works for a specific buyer_user_id (no bucketing / no hiding)
    - Mirrors existing admin_order_report router expectations
    """

    # ✅ IMPORTANT: use the REAL model names you have in your project.
    # In your repo, these might not be CouponCode / Serial.
    # If CouponCode/Serial don't exist, replace with correct ones.
    q = (
        select(
            OrderItem.id.label("order_item_id"),
            Order.id.label("order_id"),
            Order.buyer_user_id.label("raw_buyer_user_id"),
            Order.created_at.label("created_at"),
            Plan.title.label("plan_title"),
            OrderItem.amount_cents.label("amount_cents"),
            Order.currency.label("currency"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Plan, Plan.id == OrderItem.plan_id)
        .where(Order.buyer_user_id == buyer_user_id)
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

    items = []
    total_amount_cents = 0

    for r in rows:
        total_amount_cents += int(r["amount_cents"] or 0)
        items.append(
            {
                "order_item_id": int(r["order_item_id"]),
                "order_id": int(r["order_id"]),
                "created_at": r["created_at"],
                "plan_title": r["plan_title"],
                "amount_cents": int(r["amount_cents"]),
                "currency": r["currency"],
                "coupon_code": None,
                "serial_value": None,
            }
        )

    # Fetch buyer username for admin report header
    buyer_username = None
    ures = await db.execute(select(User.username).where(User.id == buyer_user_id))
    buyer_username = ures.scalar_one_or_none() or ""

    return OrderReportOut(
        buyer_user_id=int(buyer_user_id),
        username=buyer_username,
        total_amount_cents=total_amount_cents,
        currency=(currency or (rows[0]["currency"] if rows else "USD")),
        items=items,
    )