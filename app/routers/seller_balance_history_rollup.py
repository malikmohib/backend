from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.user import User
from app.schemas.wallet import WalletLedgerListOut, WalletLedgerRowOut


router = APIRouter(prefix="/sellers", tags=["Seller Balance History"])


async def _get_direct_child_by_username(
    db: AsyncSession, *, current_user_id: int, username: str
) -> User:
    res = await db.execute(select(User).where(User.username == username))
    child = res.scalar_one_or_none()

    if child is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if int(child.parent_id or 0) != int(current_user_id):
        raise HTTPException(status_code=403, detail="Not allowed. Only direct child is permitted.")

    return child


@router.get("/balance-history", response_model=WalletLedgerListOut)
async def seller_list_balance_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_seller),
    username: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    entry_kind: Optional[str] = Query(default=None),
    tx_id: Optional[str] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> WalletLedgerListOut:

    if not getattr(current_user, "path", None):
        raise HTTPException(status_code=400, detail="Current user has no path")

    seller_id = int(current_user.id)
    seller_path = str(current_user.path)
    seller_depth = int(getattr(current_user, "depth", 0))

    scope_user_id: Optional[int] = None
    scope_path: Optional[str] = None

    if username and username.strip():
        uname = username.strip()

        if uname == (current_user.username or ""):
            scope_user_id = seller_id
            scope_path = seller_path
        else:
            child = await _get_direct_child_by_username(
                db,
                current_user_id=seller_id,
                username=uname,
            )
            scope_user_id = int(child.id)
            scope_path = str(child.path)

    params = {
        "seller_username": current_user.username or "",
        "seller_id": seller_id,
        "seller_path": seller_path,
        "seller_depth": seller_depth,
        "scope_user_id": scope_user_id,
        "scope_path": scope_path,
        "offset": offset,
        "limit": limit,
    }

    # OUTER FILTERS MUST USE s.*
    where_parts: List[str] = []

    if scope_user_id is not None:
        if scope_user_id == seller_id:
            where_parts.append("s.raw_user_id = :seller_id")
        else:
            where_parts.append("s.raw_user_path <@ :scope_path")

    if date_from is not None:
        where_parts.append("s.created_at >= :date_from")
        params["date_from"] = date_from

    if date_to is not None:
        where_parts.append("s.created_at <= :date_to")
        params["date_to"] = date_to

    if entry_kind and entry_kind.strip():
        where_parts.append("s.entry_kind = :entry_kind")
        params["entry_kind"] = entry_kind.strip()

    if tx_id and tx_id.strip():
        where_parts.append("s.tx_id ILIKE :tx_like")
        params["tx_like"] = f"%{tx_id.strip()}%"

    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"

    sql = text(
        f"""
        WITH scoped AS (
            SELECT
                wl.id,
                wl.tx_id::text AS tx_id,
                wl.user_id AS raw_user_id,
                u.path AS raw_user_path,
                u.username AS raw_username,
                wl.entry_kind,
                wl.amount_cents,
                wl.currency,
                wl.related_user_id AS raw_related_user_id,
                ru.path AS raw_related_user_path,
                ru.username AS raw_related_username,
                wl.note,
                wl.created_at,
                SUM(wl.amount_cents) OVER (
                    PARTITION BY wl.user_id
                    ORDER BY wl.created_at ASC, wl.id ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS balance_after_cents
            FROM public.wallet_ledger wl
            JOIN public.users u ON u.id = wl.user_id
            LEFT JOIN public.users ru ON ru.id = wl.related_user_id
            WHERE u.path <@ :seller_path
        )
        SELECT
            s.id,
            s.tx_id,

            -- Bucketed user
            CASE
                WHEN s.raw_user_id = :seller_id THEN s.raw_user_id
                ELSE bu.id
            END AS user_id,

            CASE
                WHEN s.raw_user_id = :seller_id THEN s.raw_username
                ELSE bu.username
            END AS username,

            s.entry_kind,
            s.amount_cents,
            s.currency,

            -- Bucketed related user
            CASE
                WHEN s.raw_related_user_id IS NULL THEN NULL
                WHEN s.raw_related_user_id = :seller_id THEN :seller_id
                WHEN ru2.id IS NOT NULL THEN ru2.id
                ELSE NULL
            END AS related_user_id,

            CASE
                WHEN s.raw_related_user_id IS NULL THEN NULL
                WHEN s.raw_related_user_id = :seller_id THEN :seller_username
                WHEN ru2.username IS NOT NULL THEN ru2.username
                ELSE NULL
            END AS related_username,

            s.note,
            s.created_at,
            s.balance_after_cents

        FROM scoped s

        -- SAFE bucket join
        LEFT JOIN public.users bu
          ON s.raw_user_id <> :seller_id
         AND nlevel(s.raw_user_path::ltree) > :seller_depth
         AND bu.path = (
              (:seller_path)::ltree
              || subpath(s.raw_user_path::ltree, :seller_depth + 1, 1)
         )

        -- SAFE related bucket join
        LEFT JOIN public.users ru2
          ON s.raw_related_user_path IS NOT NULL
         AND s.raw_related_user_id <> :seller_id
         AND nlevel(s.raw_related_user_path::ltree) > :seller_depth
         AND (s.raw_related_user_path::ltree <@ (:seller_path)::ltree)
         AND ru2.path = (
              (:seller_path)::ltree
              || subpath(s.raw_related_user_path::ltree, :seller_depth + 1, 1)
         )

        WHERE {where_sql}
        ORDER BY s.created_at DESC, s.id DESC
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
                tx_id=str(r["tx_id"]),
                user_id=int(r["user_id"]) if r["user_id"] is not None else None,
                username=r["username"],
                entry_kind=r["entry_kind"],
                amount_cents=int(r["amount_cents"]),
                currency=r["currency"],
                related_user_id=int(r["related_user_id"]) if r["related_user_id"] is not None else None,
                related_username=r["related_username"],
                note=r["note"],
                created_at=r["created_at"],
                balance_after_cents=int(r["balance_after_cents"] or 0),
            )
        )

    return WalletLedgerListOut(items=items, offset=offset, limit=limit)