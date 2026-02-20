from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.db import get_db
from app.core.deps import get_current_user, require_admin
from app.models.user import User
from app.schemas.wallet import (
    AdminTopupIn,
    TxOut,
    WalletBalanceOut,
    WalletLedgerListOut,
    WalletLedgerRowOut,
)
from app.services.wallet import admin_topup, get_balance, WalletError


router = APIRouter(prefix="/admin/wallet", tags=["Admin Wallet"])


@router.get("/balance/{user_id}", response_model=WalletBalanceOut, dependencies=[Depends(require_admin)])
async def admin_get_user_balance(user_id: int, db: AsyncSession = Depends(get_db)) -> WalletBalanceOut:
    wa = await get_balance(db, user_id)
    return WalletBalanceOut(user_id=wa.user_id, balance_cents=wa.balance_cents, currency=wa.currency)


@router.post("/topup", response_model=TxOut, dependencies=[Depends(require_admin)])
async def admin_topup_user(
    payload: AdminTopupIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TxOut:
    try:
        entry = await admin_topup(
            db=db,
            admin_user=current_user,
            target_user_id=payload.user_id,
            amount_cents=payload.amount_cents,
            note=payload.note,
        )
        return TxOut(tx_id=str(entry.tx_id), created_at=entry.created_at, message="Topup successful")
    except WalletError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ledger", response_model=WalletLedgerListOut, dependencies=[Depends(require_admin)])
async def admin_list_wallet_ledger(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Frontend sends username; keep it OPTIONAL:
    username: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    entry_kind: Optional[str] = Query(default=None),
    tx_id: Optional[str] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> WalletLedgerListOut:
    """
    - If username is omitted/empty: show recent ledger for ALL sellers below current admin.
    - If username is provided: show ledger only for that seller (still must be below current admin).
    """

    if not getattr(current_user, "path", None):
        raise HTTPException(status_code=400, detail="Current user has no path; cannot scope descendants")

    where_parts: List[str] = []
    params = {
        "admin_path": current_user.path,
        "admin_id": current_user.id,
        "offset": offset,
        "limit": limit,
    }

    # Scope: sellers below this admin (descendants only)
    where_parts.append("u.role = 'seller'")
    where_parts.append("u.id <> :admin_id")
    where_parts.append("u.path <@ :admin_path")

    # Apply username filter if provided
    if username is not None and username.strip() != "":
        where_parts.append("u.username = :username")
        params["username"] = username.strip()

    if date_from is not None:
        where_parts.append("wl.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        where_parts.append("wl.created_at <= :date_to")
        params["date_to"] = date_to

    if entry_kind is not None and entry_kind != "":
        where_parts.append("wl.entry_kind = :entry_kind")
        params["entry_kind"] = entry_kind

    if tx_id is not None and tx_id != "":
        where_parts.append("wl.tx_id::text ILIKE :tx_like")
        params["tx_like"] = f"%{tx_id}%"

    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"

    # NOTE:
    # - Join users u for username
    # - Left join related user ru for related_username
    sql = text(
        f"""
        SELECT
            wl.id,
            wl.tx_id::text AS tx_id,
            wl.user_id,
            u.username AS username,
            wl.entry_kind,
            wl.amount_cents,
            wl.currency,
            wl.related_user_id,
            ru.username AS related_username,
            wl.note,
            wl.created_at,
            -- If you already store balance_after in ledger table, replace this with that column.
            NULL::bigint AS balance_after_cents
        FROM public.wallet_ledger wl
        JOIN public.users u ON u.id = wl.user_id
        LEFT JOIN public.users ru ON ru.id = wl.related_user_id
        WHERE {where_sql}
        ORDER BY wl.created_at DESC, wl.id DESC
        OFFSET :offset
        LIMIT :limit
        """
    )

    res = await db.execute(sql, params)
    rows = res.mappings().all()

    items: List[WalletLedgerRowOut] = []
    for r in rows:
        items.append(
            WalletLedgerRowOut(
                id=int(r["id"]),
                tx_id=r["tx_id"],
                user_id=int(r["user_id"]) if r["user_id"] is not None else None,
                username=r["username"],
                entry_kind=r["entry_kind"],
                amount_cents=int(r["amount_cents"]),
                currency=r["currency"],
                related_user_id=int(r["related_user_id"]) if r["related_user_id"] is not None else None,
                related_username=r["related_username"],
                note=r["note"],
                created_at=r["created_at"],
                balance_after_cents=int(r["balance_after_cents"]) if r["balance_after_cents"] is not None else None,
            )
        )

    return WalletLedgerListOut(items=items, offset=offset, limit=limit)
