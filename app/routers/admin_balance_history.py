from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.schemas.balance_history import BalanceHistoryListOut, BalanceOut, TxDetailsOut
from app.services.balance_history import (
    BalanceHistoryError,
    get_current_balance,
    get_tx_details_for_user,
    list_balance_history,
)


router = APIRouter(prefix="/admin/wallet", tags=["Admin Wallet"])


async def _get_user(db: AsyncSession, username: str) -> User:
    res = await db.execute(select(User).where(User.username == username))
    u = res.scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return u


@router.get("/balance", response_model=BalanceOut)
async def admin_user_balance(
    username: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> BalanceOut:
    u = await _get_user(db, username)
    data = await get_current_balance(db, user_id=int(u.id))
    data["username"] = u.username or username
    return BalanceOut(**data)


@router.get("/history", response_model=BalanceHistoryListOut)
async def admin_user_balance_history(
    username: str = Query(...),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    entry_kind: Optional[str] = None,
    tx_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> BalanceHistoryListOut:
    u = await _get_user(db, username)

    try:
        data = await list_balance_history(
            db,
            user_id=int(u.id),
            date_from=date_from,
            date_to=date_to,
            entry_kind=entry_kind,
            tx_id=tx_id,
            limit=limit,
            offset=offset,
        )
        return BalanceHistoryListOut(**data)
    except BalanceHistoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tx", response_model=TxDetailsOut)
async def admin_user_tx_details(
    username: str = Query(...),
    tx_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> TxDetailsOut:
    u = await _get_user(db, username)
    data = await get_tx_details_for_user(db, user_id=int(u.id), tx_id=tx_id)
    return TxDetailsOut(user_id=int(u.id), username=u.username or username, tx_id=tx_id, rows=data["rows"])
