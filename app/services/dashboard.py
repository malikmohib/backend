from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.plan import Plan
from app.models.user import User
from app.models.wallet import WalletAccount, WalletLedger


# Windows may not ship IANA tz database; ZoneInfo requires tzdata pip package.
# If tzdata is missing, we fall back to UTC so the app doesn't crash.
try:
    from zoneinfo import ZoneInfo  # py3.9+

    _KHI = ZoneInfo("Asia/Karachi")
except Exception:
    _KHI = timezone.utc


# These are confirmed in your DB dump
ADMIN_BASE_KIND = "admin_base_credit"
PROFIT_KIND = "profit_credit"

# Profit-by-seller can evolve; start with safe known kinds.
PROFIT_ENTRY_KINDS: set[str] = {PROFIT_KIND}


class DashboardError(Exception):
    pass


@dataclass
class _Range:
    period: str
    date_from: datetime | None
    date_to: datetime | None


def _utc_now_aware() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc_naive(dt: datetime) -> datetime:
    """
    Convert datetime to UTC then drop tzinfo (naive).
    This avoids asyncpg "naive vs aware" errors when DB columns are TIMESTAMP WITHOUT TIME ZONE.
    """
    if dt.tzinfo is None:
        # treat naive input as UTC (consistent behavior)
        return dt.replace(tzinfo=None)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _norm_optional(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return _to_utc_naive(dt)


def _resolve_period(period: str, date_from: datetime | None, date_to: datetime | None) -> _Range:
    """
    period: overall | today | month
    date_from/date_to override period if provided.

    Output ALWAYS returns UTC-NAIVE datetimes (safe for timestamp without time zone).
    """
    period = (period or "today").strip().lower()

    if date_from is not None or date_to is not None:
        return _Range(period="custom", date_from=_norm_optional(date_from), date_to=_norm_optional(date_to))

    if period == "overall":
        return _Range(period="overall", date_from=None, date_to=None)

    if period == "today":
        # "today" boundary computed in Asia/Karachi (if tzdata exists) else UTC
        now_local = datetime.now(_KHI)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        date_from_aware_utc = start_local.astimezone(timezone.utc)
        date_to_aware_utc = _utc_now_aware()

        return _Range(
            period="today",
            date_from=_to_utc_naive(date_from_aware_utc),
            date_to=_to_utc_naive(date_to_aware_utc),
        )

    if period == "month":
        end_aware = _utc_now_aware()
        start_aware = end_aware - timedelta(days=30)
        return _Range(period="month", date_from=_to_utc_naive(start_aware), date_to=_to_utc_naive(end_aware))

    # default safe
    now_local = datetime.now(_KHI)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    date_from_aware_utc = start_local.astimezone(timezone.utc)
    date_to_aware_utc = _utc_now_aware()
    return _Range(period="today", date_from=_to_utc_naive(date_from_aware_utc), date_to=_to_utc_naive(date_to_aware_utc))


async def _username_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    ids = [int(x) for x in set(user_ids) if x is not None]
    if not ids:
        return {}
    res = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {int(r[0]): (r[1] or "") for r in res.all()}


async def _direct_scope_user_ids(db: AsyncSession, *, current_user_id: int) -> list[int]:
    """
    Direct scope for seller dashboard: self + direct children only.
    """
    res = await db.execute(select(User.id).where(User.parent_id == current_user_id))
    child_ids = [int(x) for x in res.scalars().all()]
    return [int(current_user_id)] + child_ids


def _apply_time_filter(stmt, col, r: _Range):
    if r.date_from is not None:
        stmt = stmt.where(col >= r.date_from)
    if r.date_to is not None:
        stmt = stmt.where(col <= r.date_to)
    return stmt


# -------------------------
# SALES (orders-based)
# -------------------------

async def sales_totals(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    buyer_user_ids: list[int] | None = None,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = []
    if buyer_user_ids is not None:
        filters.append(Order.buyer_user_id.in_([int(x) for x in buyer_user_ids]))

    stmt = select(
        func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
        func.coalesce(func.count(Order.id), 0).label("orders_count"),
        func.coalesce(func.sum(Order.quantity), 0).label("units"),
    ).where(*filters)

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    row = res.first() or (0, 0, 0)

    return {
        "period": r.period,
        "date_from": r.date_from,
        "date_to": r.date_to,
        "total_sales_cents": int(row[0] or 0),
        "total_orders": int(row[1] or 0),
        "total_units": int(row[2] or 0),
    }


async def sales_by_plan(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    buyer_user_ids: list[int] | None = None,
    limit: int = 50,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = []
    if buyer_user_ids is not None:
        filters.append(Order.buyer_user_id.in_([int(x) for x in buyer_user_ids]))

    stmt = (
        select(
            Order.plan_id.label("plan_id"),
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
            Plan.title.label("plan_title"),
            Plan.category.label("plan_category"),
        )
        .select_from(Order)
        .join(Plan, Plan.id == Order.plan_id)
        .where(*filters)
        .group_by(Order.plan_id, Plan.title, Plan.category)
        .order_by(desc("sales_cents"))
        .limit(limit)
    )

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    rows = res.all()

    items = []
    for x in rows:
        items.append(
            {
                "plan_id": int(x.plan_id),
                "plan_title": x.plan_title or "",
                "plan_category": x.plan_category or "",
                "sales_cents": int(x.sales_cents or 0),
                "orders_count": int(x.orders_count or 0),
                "units": int(x.units or 0),
            }
        )

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def sales_by_seller(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    buyer_user_ids: list[int] | None = None,
    limit: int = 50,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = []
    if buyer_user_ids is not None:
        filters.append(Order.buyer_user_id.in_([int(x) for x in buyer_user_ids]))

    stmt = (
        select(
            Order.buyer_user_id.label("user_id"),
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
        )
        .where(*filters)
        .group_by(Order.buyer_user_id)
        .order_by(desc("sales_cents"))
        .limit(limit)
    )

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    rows = res.all()

    user_ids = [int(x.user_id) for x in rows if x.user_id is not None]
    uname = await _username_map(db, user_ids)

    items = []
    for x in rows:
        uid = int(x.user_id)
        items.append(
            {
                "user_id": uid,
                "username": uname.get(uid, ""),
                "sales_cents": int(x.sales_cents or 0),
                "orders_count": int(x.orders_count or 0),
                "units": int(x.units or 0),
            }
        )

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


# -------------------------
# PROFIT (ledger-based)
# -------------------------

async def profit_by_seller(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    user_ids: list[int] | None = None,
    limit: int = 50,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = [WalletLedger.entry_kind.in_(sorted(PROFIT_ENTRY_KINDS)), WalletLedger.amount_cents > 0]
    if user_ids is not None:
        filters.append(WalletLedger.user_id.in_([int(x) for x in user_ids]))

    stmt = (
        select(
            WalletLedger.user_id.label("user_id"),
            func.coalesce(func.sum(WalletLedger.amount_cents), 0).label("profit_cents"),
        )
        .where(*filters)
        .group_by(WalletLedger.user_id)
        .order_by(desc("profit_cents"))
        .limit(limit)
    )

    stmt = _apply_time_filter(stmt, WalletLedger.created_at, r)

    res = await db.execute(stmt)
    rows = res.all()

    ids = [int(x.user_id) for x in rows if x.user_id is not None]
    uname = await _username_map(db, ids)

    items = []
    for x in rows:
        uid = int(x.user_id)
        items.append({"user_id": uid, "username": uname.get(uid, ""), "profit_cents": int(x.profit_cents or 0)})

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def admin_income_totals(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    base_case = case((WalletLedger.entry_kind == ADMIN_BASE_KIND, WalletLedger.amount_cents), else_=0)
    profit_case = case((WalletLedger.entry_kind == PROFIT_KIND, WalletLedger.amount_cents), else_=0)

    stmt = select(
        func.coalesce(func.sum(base_case), 0),
        func.coalesce(func.sum(profit_case), 0),
    ).where(WalletLedger.amount_cents > 0)

    stmt = _apply_time_filter(stmt, WalletLedger.created_at, r)

    res = await db.execute(stmt)
    row = res.first() or (0, 0)

    base_cents = int(row[0] or 0)
    profit_cents = int(row[1] or 0)

    return {
        "period": r.period,
        "date_from": r.date_from,
        "date_to": r.date_to,
        "admin_base_cents": base_cents,
        "admin_profit_cents": profit_cents,
        "total_profit_cents": profit_cents,
    }


# -------------------------
# BALANCES (wallet_accounts)
# -------------------------

async def balances_overview(
    db: AsyncSession,
    *,
    user_ids: list[int] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    filters = []
    if user_ids is not None:
        filters.append(WalletAccount.user_id.in_([int(x) for x in user_ids]))

    total_stmt = select(func.count()).select_from(WalletAccount).where(*filters)
    total_res = await db.execute(total_stmt)
    total = int(total_res.scalar() or 0)

    stmt = (
        select(WalletAccount, User)
        .select_from(WalletAccount)
        .join(User, User.id == WalletAccount.user_id)
        .where(*filters)
        .order_by(WalletAccount.balance_cents.desc(), WalletAccount.user_id.asc())
        .limit(limit)
        .offset(offset)
    )

    res = await db.execute(stmt)
    rows = res.all()

    items = []
    for wa, u in rows:
        items.append(
            {
                "user_id": int(wa.user_id),
                "username": u.username or "",
                "role": getattr(u, "role", "") or "",
                "balance_cents": int(wa.balance_cents or 0),
                "currency": wa.currency or "USD",
                "updated_at": wa.updated_at,
            }
        )

    return {"items": items, "limit": limit, "offset": offset, "total": total}


# -------------------------
# SUMMARY (cards)
# -------------------------

async def dashboard_summary_admin(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    totals = await sales_totals(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=None)
    income = await admin_income_totals(db, period=period, date_from=date_from, date_to=date_to)

    plan_rows = await sales_by_plan(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=None, limit=1)
    seller_rows = await sales_by_seller(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=None, limit=1)

    best_plan = (plan_rows["items"][0] if plan_rows["items"] else {})
    best_seller = (seller_rows["items"][0] if seller_rows["items"] else {})

    return {
        "period": totals["period"],
        "date_from": totals["date_from"],
        "date_to": totals["date_to"],
        "total_sales_cents": totals["total_sales_cents"],
        "total_orders": totals["total_orders"],
        "total_units": totals["total_units"],
        "admin_base_cents": income["admin_base_cents"],
        "admin_profit_cents": income["admin_profit_cents"],
        "total_profit_cents": income["total_profit_cents"],
        "best_seller": best_seller or {},
        "best_plan": best_plan or {},
    }


async def dashboard_summary_seller_direct(
    db: AsyncSession,
    *,
    current_user_id: int,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    scope_ids = await _direct_scope_user_ids(db, current_user_id=current_user_id)

    totals = await sales_totals(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=scope_ids)

    profit_rows = await profit_by_seller(db, period=period, date_from=date_from, date_to=date_to, user_ids=scope_ids, limit=1000)
    profit_total = sum(int(x["profit_cents"]) for x in profit_rows["items"])

    plan_rows = await sales_by_plan(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=scope_ids, limit=1)
    seller_rows = await sales_by_seller(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=scope_ids, limit=1)

    best_plan = (plan_rows["items"][0] if plan_rows["items"] else {})
    best_seller = (seller_rows["items"][0] if seller_rows["items"] else {})

    return {
        "period": totals["period"],
        "date_from": totals["date_from"],
        "date_to": totals["date_to"],
        "total_sales_cents": totals["total_sales_cents"],
        "total_orders": totals["total_orders"],
        "total_units": totals["total_units"],
        "admin_base_cents": 0,
        "admin_profit_cents": 0,
        "total_profit_cents": int(profit_total),
        "best_seller": best_seller or {},
        "best_plan": best_plan or {},
    }
