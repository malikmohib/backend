from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.plan import Plan
from app.models.wallet import WalletAccount, WalletLedger
from app.services.wallet import _ensure_wallet_account, _lock_accounts, USD, InsufficientBalance

# IMPORTANT:
# These class names MUST match your existing app/models/pricing.py
from app.models.pricing import AdminPlanBasePrice, SellerEdgePlanPrice

# Module E
from app.models.coupon import Coupon
from app.models.coupon_event import CouponEvent
from app.models.order import Order
from app.models.order_item import OrderItem


class PurchaseError(Exception):
    pass


def _now_utc() -> datetime:
    return datetime.utcnow()


async def _get_user(db: AsyncSession, user_id: int) -> User:
    res = await db.execute(select(User).where(User.id == user_id))
    u = res.scalar_one_or_none()
    if u is None:
        raise PurchaseError("User not found.")
    return u


async def _get_plan(db: AsyncSession, plan_id: int) -> Plan:
    res = await db.execute(select(Plan).where(Plan.id == plan_id))
    p = res.scalar_one_or_none()
    if p is None:
        raise PurchaseError("Plan not found.")
    if not p.is_active:
        raise PurchaseError("Plan is not active.")
    return p


async def _get_admin_base_price_cents(db: AsyncSession, plan_id: int) -> int:
    res = await db.execute(
        select(AdminPlanBasePrice.base_price_cents)
        .where(AdminPlanBasePrice.plan_id == plan_id)
    )
    v = res.scalar_one_or_none()
    if v is None:
        raise PurchaseError("Admin base price missing for plan.")
    return int(v)


async def _get_edge_price_cents(db: AsyncSession, parent_id: int, child_id: int, plan_id: int) -> int:
    res = await db.execute(
        select(SellerEdgePlanPrice.price_cents)
        .where(
            SellerEdgePlanPrice.parent_user_id == parent_id,
            SellerEdgePlanPrice.child_user_id == child_id,
            SellerEdgePlanPrice.plan_id == plan_id,
        )
    )
    v = res.scalar_one_or_none()
    if v is None:
        raise PurchaseError(f"Edge price missing for parent={parent_id} child={child_id} plan={plan_id}.")
    return int(v)


async def purchase_plan_and_distribute(
    db: AsyncSession,
    buyer: User,
    plan_id: int,
    quantity: int = 1,
    note: str | None = None,
) -> dict:
    """
    Buyer is charged using direct parent -> buyer edge price for plan.

    Distribution:
      For each ancestor:
        profit = (sell price to child) - (their own cost)
      Admin gets:
        base cost (Option A) + its own profit

    Ensures: sum(credits) == purchase debit.

    Module E extension:
      - quantity support
      - debit/credits scale by quantity
      - create orders + order_items linked to tx_id
      - generate N coupons immediately (no inventory) and assign to buyer
      - single commit (atomic)
    """
    if quantity < 1:
        raise PurchaseError("quantity must be >= 1.")

    await _get_plan(db, plan_id)

    if buyer.parent_id is None:
        raise PurchaseError("Buyer has no parent; cannot purchase.")

    # Unit purchase price = buyer direct parent edge price
    unit_price_cents = await _get_edge_price_cents(db, buyer.parent_id, buyer.id, plan_id)
    total_paid_cents = int(unit_price_cents) * int(quantity)

    # Admin base (unit)
    base_cents = await _get_admin_base_price_cents(db, plan_id)

    # Build unit credits_by_user (unit profits + unit admin base)
    credits_by_user_unit: dict[int, int] = {}

    current_child = buyer

    while True:
        parent_id = current_child.parent_id
        if parent_id is None:
            raise PurchaseError("Tree broken: reached user without parent before admin.")

        parent = await _get_user(db, parent_id)

        sell_price = await _get_edge_price_cents(db, parent.id, current_child.id, plan_id)

        # parent's cost:
        if parent.role == "admin":
            cost = base_cents
        else:
            if parent.parent_id is None:
                raise PurchaseError("Non-admin parent has no parent_id; invalid tree.")
            cost = await _get_edge_price_cents(db, parent.parent_id, parent.id, plan_id)

        profit = sell_price - cost
        if profit < 0:
            raise PurchaseError("Pricing invalid: negative profit detected in chain.")

        if profit > 0:
            credits_by_user_unit[parent.id] = credits_by_user_unit.get(parent.id, 0) + profit

        if parent.role == "admin":
            # Option A: admin receives base cost (unit)
            credits_by_user_unit[parent.id] = credits_by_user_unit.get(parent.id, 0) + base_cents
            break

        current_child = parent

    # Scale credits for quantity
    credits_by_user_scaled: dict[int, int] = {
        uid: int(cents) * int(quantity) for uid, cents in credits_by_user_unit.items()
    }

    # Lock all accounts involved
    all_user_ids = [buyer.id] + list(credits_by_user_scaled.keys())

    # ✅ generate one tx_id for ALL ledger rows (purchase debit + all credits + order linkage)
    tx_id = uuid4()

    try:
        # ensure buyer account exists
        await _ensure_wallet_account(db, buyer.id)

        # lock accounts
        accounts = await _lock_accounts(db, all_user_ids)

        buyer_acc = accounts[buyer.id]
        if buyer_acc.balance_cents < total_paid_cents:
            raise InsufficientBalance("Insufficient balance for purchase.")

        # 1) debit buyer
        await db.execute(
            update(WalletAccount)
            .where(WalletAccount.user_id == buyer.id)
            .values(
                balance_cents=buyer_acc.balance_cents - total_paid_cents,
                updated_at=_now_utc(),
            )
        )

        debit_entry = WalletLedger(
            tx_id=tx_id,
            user_id=buyer.id,
            entry_kind="purchase_debit",
            amount_cents=-total_paid_cents,
            currency=USD,
            related_user_id=buyer.parent_id,
            plan_id=plan_id,
            note=note,
            meta={
                "plan_id": plan_id,
                "unit_price_cents": unit_price_cents,
                "quantity": quantity,
                "total_paid_cents": total_paid_cents,
            },
        )
        db.add(debit_entry)

        # 2) credits
        total_credits = 0

        for uid, cents in credits_by_user_scaled.items():
            total_credits += cents

            acc = accounts[uid]
            await db.execute(
                update(WalletAccount)
                .where(WalletAccount.user_id == uid)
                .values(
                    balance_cents=acc.balance_cents + cents,
                    updated_at=_now_utc(),
                )
            )

            user_obj = await _get_user(db, uid)

            if user_obj.role == "admin":
                # admin credit contains base*qty + profit
                admin_total = cents
                base_total = int(base_cents) * int(quantity)
                admin_profit = max(0, admin_total - base_total)

                base_entry = WalletLedger(
                    tx_id=tx_id,
                    user_id=uid,
                    entry_kind="admin_base_credit",
                    amount_cents=base_total,
                    currency=USD,
                    related_user_id=buyer.id,
                    plan_id=plan_id,
                    note="Admin base cost credit",
                    meta={"plan_id": plan_id, "quantity": quantity},
                )
                db.add(base_entry)

                if admin_profit > 0:
                    profit_entry = WalletLedger(
                        tx_id=tx_id,
                        user_id=uid,
                        entry_kind="profit_credit",
                        amount_cents=admin_profit,
                        currency=USD,
                        related_user_id=buyer.id,
                        plan_id=plan_id,
                        note="Admin profit credit",
                        meta={"plan_id": plan_id, "quantity": quantity},
                    )
                    db.add(profit_entry)
            else:
                profit_entry = WalletLedger(
                    tx_id=tx_id,
                    user_id=uid,
                    entry_kind="profit_credit",
                    amount_cents=cents,
                    currency=USD,
                    related_user_id=buyer.id,
                    plan_id=plan_id,
                    note="Profit credit",
                    meta={"plan_id": plan_id, "quantity": quantity},
                )
                db.add(profit_entry)

        if total_credits != total_paid_cents:
            raise PurchaseError(
                f"Internal mismatch: credits({total_credits}) != purchase({total_paid_cents})."
            )

        # Module E: create order row (same tx_id)
        order = Order(
            tx_id=tx_id,
            buyer_user_id=buyer.id,
            plan_id=plan_id,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
            total_paid_cents=total_paid_cents,
            currency="USD",
            status="paid",
        )
        db.add(order)
        await db.flush()  # ensures order.id and order.order_no

        # Generate coupons immediately (no inventory), assign to buyer, create items
        coupon_codes: list[str] = []

        for _ in range(quantity):
            code: str | None = None

            # Avoid mid-loop rollback: pre-check for collisions
            for _attempt in range(20):
                candidate = f"Certify-{uuid4().hex[:8]}"
                exists = await db.execute(
                    select(Coupon.coupon_code).where(Coupon.coupon_code == candidate)
                )
                if exists.scalar_one_or_none() is None:
                    code = candidate
                    break

            if code is None:
                raise PurchaseError("Failed to generate unique coupon code.")

            coupon = Coupon(
                coupon_code=code,
                plan_id=plan_id,
                status="unused",
                created_by_user_id=buyer.id,
                owner_user_id=buyer.id,
                notes=note,
            )
            db.add(coupon)

            db.add(
                OrderItem(
                    order_id=order.id,
                    coupon_code=code,
                )
            )

            # Keep coupon timeline consistent
            db.add(
                CouponEvent(
                    coupon_code=code,
                    event_type="generated",
                    actor_user_id=buyer.id,
                    meta={
                        "source": "purchase",
                        "order_no": order.order_no,
                        "tx_id": str(tx_id),
                        "plan_id": plan_id,
                        "quantity": quantity,
                    },
                )
            )

            coupon_codes.append(code)

        await db.commit()

        keys_text = "\n".join(coupon_codes)

        return {
            "tx_id": str(tx_id),
            "plan_id": plan_id,
            "buyer_user_id": buyer.id,
            # Backward compatible: old field name, still unit
            "purchase_price_cents": unit_price_cents,
            # Keep old (unit) credits dict unchanged for existing clients,
            # but also used to compute scaled credits in ledgers.
            "credits_by_user": credits_by_user_unit,
            # Module E
            "order_no": order.order_no,
            "quantity": quantity,
            "total_paid_cents": total_paid_cents,
            "coupon_codes": coupon_codes,
            "keys_text": keys_text,
        }

    except Exception:
        await db.rollback()
        raise
