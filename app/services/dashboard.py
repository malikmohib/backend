from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, String, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.order import Order
from app.models.plan import Plan
from app.models.user import User
from app.models.wallet import WalletAccount, WalletLedger
from sqlalchemy import Integer, String, case, cast, desc, func, select, literal
from sqlalchemy.types import UserDefinedType
from sqlalchemy import literal


class LTREE(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return "LTREE"
    

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


def _apply_time_filter(stmt, dt_col, r: _Range):
    if r.date_from is not None:
        stmt = stmt.where(dt_col >= r.date_from)
    if r.date_to is not None:
        stmt = stmt.where(dt_col <= r.date_to)
    return stmt


async def _username_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    ids = [int(x) for x in set(user_ids) if x is not None]
    if not ids:
        return {}
    res = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {int(r[0]): (r[1] or "") for r in res.all()}


async def _direct_scope_user_ids(db: AsyncSession, *, current_user_id: int) -> list[int]:
    """
    Direct scope for seller pages where structure must not expose grandchildren:
    self + direct children only.
    """
    res = await db.execute(select(User.id).where(User.parent_id == current_user_id))
    child_ids = [int(x) for x in res.scalars().all()]
    return [int(current_user_id)] + child_ids


def _ltree_is_descendant_expr(user_path_col, ancestor_path: str):
    user_path_ltree = cast(user_path_col, LTREE())
    ancestor_ltree = cast(literal(str(ancestor_path)), LTREE())
    return user_path_ltree.op("<@")(ancestor_ltree)


def _direct_child_bucket_user_id_expr(*, buyer_id_col, buyer_path_col, current_user_id: int, current_user_path: str):
    buyer_path_ltree = cast(buyer_path_col, LTREE())
    scope_ltree = cast(literal(str(current_user_path)), LTREE())

    child_label_ltree = func.subpath(buyer_path_ltree, func.nlevel(scope_ltree), 1)
    child_label_txt = cast(child_label_ltree, String)
    child_id_txt = func.substr(child_label_txt, 2)
    child_id_int = cast(child_id_txt, Integer)

    return case(
        (buyer_id_col == int(current_user_id), int(current_user_id)),
        else_=child_id_int,
    )


async def sales_totals_subtree(
    db: AsyncSession,
    *,
    current_user_path: str,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    """
    Seller rollup totals: include purchases made by ANY descendant (direct + indirect).
    """
    r = _resolve_period(period, date_from, date_to)

    Buyer = aliased(User)

    stmt = (
        select(
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
        )
        .select_from(Order)
        .join(Buyer, Buyer.id == Order.buyer_user_id)
        .where(_ltree_is_descendant_expr(Buyer.path, current_user_path))
    )

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


async def sales_by_plan_subtree(
    db: AsyncSession,
    *,
    current_user_path: str,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int = 50,
) -> dict:
    """
    Seller rollup: group by plan using purchases made by ANY descendant.
    """
    r = _resolve_period(period, date_from, date_to)

    Buyer = aliased(User)

    stmt = (
        select(
            Plan.id.label("plan_id"),
            Plan.title.label("plan_title"),
            Plan.category.label("plan_category"),
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
        )
        .select_from(Order)
        .join(Plan, Plan.id == Order.plan_id)
        .join(Buyer, Buyer.id == Order.buyer_user_id)
        .where(_ltree_is_descendant_expr(Buyer.path, current_user_path))
        .group_by(Plan.id, Plan.title, Plan.category)
        .order_by(desc("sales_cents"))
        .limit(int(limit))
    )

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    items = []
    for row in res.all():
        items.append(
            {
                "plan_id": int(row.plan_id),
                "plan_title": row.plan_title or "",
                "plan_category": row.plan_category or "",
                "sales_cents": int(row.sales_cents or 0),
                "orders_count": int(row.orders_count or 0),
                "units": int(row.units or 0),
            }
        )

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def sales_by_seller_rollup_direct(
    db: AsyncSession,
    *,
    current_user_id: int,
    current_user_path: str,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int = 50,
) -> dict:
    """
    Seller rollup: group ALL descendant purchases under (self + direct children) buckets.
    This includes grandchildren but does not reveal them.
    """
    r = _resolve_period(period, date_from, date_to)

    Buyer = aliased(User)

    bucket_user_id = _direct_child_bucket_user_id_expr(
        buyer_id_col=Buyer.id,
        buyer_path_col=Buyer.path,
        current_user_id=int(current_user_id),
        current_user_path=str(current_user_path),
    ).label("bucket_user_id")

    stmt = (
        select(
            bucket_user_id,
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
        )
        .select_from(Order)
        .join(Buyer, Buyer.id == Order.buyer_user_id)
        .where(_ltree_is_descendant_expr(Buyer.path, current_user_path))
        .group_by(bucket_user_id)
        .order_by(desc("sales_cents"))
        .limit(int(limit))
    )

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    rows = res.all()

    bucket_ids = [int(r[0]) for r in rows if r[0] is not None]
    uname = await _username_map(db, bucket_ids)

    items = []
    for row in rows:
        bid = row[0]
        if bid is None:
            continue
        bid_int = int(bid)
        items.append(
            {
                "user_id": bid_int,
                "username": uname.get(bid_int, ""),
                "sales_cents": int(row.sales_cents or 0),
                "orders_count": int(row.orders_count or 0),
                "units": int(row.units or 0),
            }
        )

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def dashboard_summary_seller_rollup(
    db: AsyncSession,
    *,
    current_user: User,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    """
    Seller dashboard summary (rollup-safe):
      - Sales/orders/units are rolled up from full subtree (direct + indirect)
      - "best_seller" is bucketed to self + direct children (grandchildren rolled up)
      - Profit is ledger-based (self + direct children)
    """
    scope_ids = await _direct_scope_user_ids(db, current_user_id=int(current_user.id))

    totals = await sales_totals_subtree(
        db,
        current_user_path=str(current_user.path),
        period=period,
        date_from=date_from,
        date_to=date_to,
    )

    profit_rows = await profit_by_seller(db, period=period, date_from=date_from, date_to=date_to, user_ids=scope_ids, limit=1000)
    profit_total = sum(int(x["profit_cents"]) for x in profit_rows["items"])

    plan_rows = await sales_by_plan_subtree(
        db,
        current_user_path=str(current_user.path),
        period=period,
        date_from=date_from,
        date_to=date_to,
        limit=1,
    )
    seller_rows = await sales_by_seller_rollup_direct(
        db,
        current_user_id=int(current_user.id),
        current_user_path=str(current_user.path),
        period=period,
        date_from=date_from,
        date_to=date_to,
        limit=1,
    )

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
    buyer_user_ids: list[int] | None,
    limit: int = 50,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = []
    if buyer_user_ids is not None:
        filters.append(Order.buyer_user_id.in_([int(x) for x in buyer_user_ids]))

    stmt = (
        select(
            Plan.id.label("plan_id"),
            Plan.title.label("plan_title"),
            Plan.category.label("plan_category"),
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
        )
        .select_from(Order)
        .join(Plan, Plan.id == Order.plan_id)
        .where(*filters)
        .group_by(Plan.id, Plan.title, Plan.category)
        .order_by(desc("sales_cents"))
        .limit(int(limit))
    )

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    items = []
    for row in res.all():
        items.append(
            {
                "plan_id": int(row.plan_id),
                "plan_title": row.plan_title or "",
                "plan_category": row.plan_category or "",
                "sales_cents": int(row.sales_cents or 0),
                "orders_count": int(row.orders_count or 0),
                "units": int(row.units or 0),
            }
        )

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def sales_by_seller(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    buyer_user_ids: list[int] | None,
    limit: int = 50,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = []
    if buyer_user_ids is not None:
        filters.append(Order.buyer_user_id.in_([int(x) for x in buyer_user_ids]))

    stmt = (
        select(
            User.id.label("user_id"),
            User.username.label("username"),
            func.coalesce(func.sum(Order.total_paid_cents), 0).label("sales_cents"),
            func.coalesce(func.count(Order.id), 0).label("orders_count"),
            func.coalesce(func.sum(Order.quantity), 0).label("units"),
        )
        .select_from(Order)
        .join(User, User.id == Order.buyer_user_id)
        .where(*filters)
        .group_by(User.id, User.username)
        .order_by(desc("sales_cents"))
        .limit(int(limit))
    )

    stmt = _apply_time_filter(stmt, Order.created_at, r)

    res = await db.execute(stmt)
    items = []
    for row in res.all():
        items.append(
            {
                "user_id": int(row.user_id),
                "username": row.username or "",
                "sales_cents": int(row.sales_cents or 0),
                "orders_count": int(row.orders_count or 0),
                "units": int(row.units or 0),
            }
        )

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def profit_by_seller(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    user_ids: list[int] | None,
    limit: int = 50,
) -> dict:
    r = _resolve_period(period, date_from, date_to)

    filters = [WalletLedger.entry_kind.in_(sorted(PROFIT_ENTRY_KINDS))]
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
        .limit(int(limit))
    )

    stmt = _apply_time_filter(stmt, WalletLedger.created_at, r)

    res = await db.execute(stmt)
    rows = res.all()

    ids = [int(r.user_id) for r in rows if r.user_id is not None]
    uname = await _username_map(db, ids)

    items = []
    for row in rows:
        uid = row.user_id
        if uid is None:
            continue
        uid_int = int(uid)
        items.append({"user_id": uid_int, "username": uname.get(uid_int, ""), "profit_cents": int(row.profit_cents or 0)})

    return {"period": r.period, "date_from": r.date_from, "date_to": r.date_to, "items": items}


async def balances_overview(
    db: AsyncSession,
    *,
    user_ids: list[int] | None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    filters = []
    if user_ids is not None:
        filters.append(WalletAccount.user_id.in_([int(x) for x in user_ids]))

    # total count
    count_stmt = select(func.count(WalletAccount.user_id)).where(*filters)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    stmt = (
        select(
            WalletAccount.user_id,
            User.username,
            User.role,
            WalletAccount.balance_cents,
            WalletAccount.currency,
            WalletAccount.updated_at,
        )
        .select_from(WalletAccount)
        .join(User, User.id == WalletAccount.user_id)
        .where(*filters)
        .order_by(desc(WalletAccount.updated_at), WalletAccount.user_id)
        .limit(int(limit))
        .offset(int(offset))
    )

    res = await db.execute(stmt)
    items = []
    for row in res.all():
        items.append(
            {
                "user_id": int(row.user_id),
                "username": row.username or "",
                "role": row.role or "",
                "balance_cents": int(row.balance_cents or 0),
                "currency": row.currency or "USD",
                "updated_at": row.updated_at,
            }
        )

    return {"items": items, "limit": int(limit), "offset": int(offset), "total": total}


async def dashboard_summary_admin(
    db: AsyncSession,
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    totals = await sales_totals(db, period=period, date_from=date_from, date_to=date_to, buyer_user_ids=None)

    # Admin base+profit totals from ledger
    r = _resolve_period(period, date_from, date_to)

    base_stmt = select(func.coalesce(func.sum(WalletLedger.amount_cents), 0)).where(WalletLedger.entry_kind == ADMIN_BASE_KIND)
    base_stmt = _apply_time_filter(base_stmt, WalletLedger.created_at, r)
    base_total = int((await db.execute(base_stmt)).scalar_one() or 0)

    profit_stmt = select(func.coalesce(func.sum(WalletLedger.amount_cents), 0)).where(WalletLedger.entry_kind == PROFIT_KIND)
    profit_stmt = _apply_time_filter(profit_stmt, WalletLedger.created_at, r)
    profit_total = int((await db.execute(profit_stmt)).scalar_one() or 0)

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
        "admin_base_cents": int(base_total),
        "admin_profit_cents": int(profit_total),
        "total_profit_cents": int(profit_total),
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