from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan
from app.models.user import User
from app.models.wallet import WalletAccount, WalletLedger


class BalanceHistoryError(Exception):
    pass


async def _get_user_by_username(db: AsyncSession, username: str) -> User:
    res = await db.execute(select(User).where(User.username == username))
    u = res.scalar_one_or_none()
    if u is None:
        raise BalanceHistoryError("User not found.")
    return u


async def _username_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    ids = [int(x) for x in set(user_ids) if x is not None]
    if not ids:
        return {}
    res = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {int(r[0]): (r[1] or "") for r in res.all()}


async def _plan_title_map(db: AsyncSession, plan_ids: list[int]) -> dict[int, str]:
    ids = [int(x) for x in set(plan_ids) if x is not None]
    if not ids:
        return {}
    res = await db.execute(select(Plan.id, Plan.title).where(Plan.id.in_(ids)))
    return {int(r[0]): (r[1] or "") for r in res.all()}


async def get_current_balance(db: AsyncSession, *, user_id: int) -> dict:
    res = await db.execute(select(WalletAccount).where(WalletAccount.user_id == user_id))
    acc = res.scalar_one_or_none()
    if acc is None:
        # if account doesn't exist yet, treat as 0
        return {
            "user_id": int(user_id),
            "username": "",
            "balance_cents": 0,
            "currency": "USD",
            "updated_at": None,
        }

    return {
        "user_id": int(acc.user_id),
        "username": "",
        "balance_cents": int(acc.balance_cents),
        "currency": acc.currency,
        "updated_at": acc.updated_at,
    }


async def list_balance_history(
    db: AsyncSession,
    *,
    user_id: int,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    entry_kind: Optional[str] = None,
    tx_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    filters = [WalletLedger.user_id == user_id]

    if date_from is not None:
        filters.append(WalletLedger.created_at >= date_from)
    if date_to is not None:
        filters.append(WalletLedger.created_at <= date_to)
    if entry_kind is not None:
        filters.append(WalletLedger.entry_kind == entry_kind)
    if tx_id is not None:
        filters.append(WalletLedger.tx_id == tx_id)

    total_stmt = select(func.count()).select_from(WalletLedger).where(*filters)
    total_res = await db.execute(total_stmt)
    total = int(total_res.scalar() or 0)

    # running balance for this user ordered by time
    running_balance = func.sum(WalletLedger.amount_cents).over(
        partition_by=WalletLedger.user_id,
        order_by=(WalletLedger.created_at.asc(), WalletLedger.id.asc()),
    )

    cte = (
        select(
            WalletLedger.id.label("id"),
            WalletLedger.created_at.label("created_at"),
            WalletLedger.tx_id.label("tx_id"),
            WalletLedger.entry_kind.label("entry_kind"),
            WalletLedger.amount_cents.label("amount_cents"),
            WalletLedger.currency.label("currency"),
            WalletLedger.related_user_id.label("related_user_id"),
            WalletLedger.plan_id.label("plan_id"),
            WalletLedger.note.label("note"),
            WalletLedger.meta.label("meta"),
            running_balance.label("balance_after_cents"),
        )
        .where(*filters)
        .order_by(WalletLedger.created_at.asc(), WalletLedger.id.asc())
        .cte("ledger_with_balance")
    )

    # paginate newest-first for UI
    page_stmt = (
        select(cte)
        .order_by(cte.c.created_at.desc(), cte.c.id.desc())
        .limit(limit)
        .offset(offset)
    )

    res = await db.execute(page_stmt)
    rows = res.mappings().all()

    related_ids = [int(r["related_user_id"]) for r in rows if r["related_user_id"] is not None]
    plan_ids = [int(r["plan_id"]) for r in rows if r["plan_id"] is not None]

    uname = await _username_map(db, related_ids)
    ptitle = await _plan_title_map(db, plan_ids)

    items = []
    for r in rows:
        rid = r["related_user_id"]
        pid = r["plan_id"]
        items.append(
            {
                "id": int(r["id"]),
                "created_at": r["created_at"],
                "tx_id": str(r["tx_id"]),
                "entry_kind": r["entry_kind"],
                "amount_cents": int(r["amount_cents"]),
                "balance_after_cents": int(r["balance_after_cents"] or 0),
                "currency": r["currency"],
                "related_user_id": int(rid) if rid is not None else None,
                "related_username": uname.get(int(rid), "") if rid is not None else "",
                "plan_id": int(pid) if pid is not None else None,
                "plan_title": ptitle.get(int(pid), "") if pid is not None else "",
                "note": r["note"],
                "meta": r["meta"] or {},
            }
        )

    return {"items": items, "limit": limit, "offset": offset, "total": total}


async def get_tx_details_for_user(db: AsyncSession, *, user_id: int, tx_id: str) -> dict:
    # all rows for this user+tx
    stmt = (
        select(WalletLedger)
        .where(WalletLedger.user_id == user_id, WalletLedger.tx_id == tx_id)
        .order_by(WalletLedger.created_at.asc(), WalletLedger.id.asc())
    )
    res = await db.execute(stmt)
    ledgers = res.scalars().all()

    related_ids = [int(x.related_user_id) for x in ledgers if x.related_user_id is not None]
    plan_ids = [int(x.plan_id) for x in ledgers if x.plan_id is not None]

    uname = await _username_map(db, related_ids)
    ptitle = await _plan_title_map(db, plan_ids)

    rows = []
    for x in ledgers:
        rid = x.related_user_id
        pid = x.plan_id
        rows.append(
            {
                "id": int(x.id),
                "created_at": x.created_at,
                "tx_id": str(x.tx_id),
                "entry_kind": x.entry_kind,
                "amount_cents": int(x.amount_cents),
                # tx details doesn't need running balance; keep 0
                "balance_after_cents": 0,
                "currency": x.currency,
                "related_user_id": int(rid) if rid is not None else None,
                "related_username": uname.get(int(rid), "") if rid is not None else "",
                "plan_id": int(pid) if pid is not None else None,
                "plan_title": ptitle.get(int(pid), "") if pid is not None else "",
                "note": x.note,
                "meta": x.meta or {},
            }
        )

    return {"tx_id": tx_id, "rows": rows}
