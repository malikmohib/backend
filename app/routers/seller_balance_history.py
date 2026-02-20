from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.balance_history import BalanceHistoryListOut, BalanceOut, TxDetailsOut
from app.services.balance_history import (
    BalanceHistoryError,
    get_current_balance,
    get_tx_details_for_user,
    list_balance_history,
)


router = APIRouter(prefix="/sellers/wallet", tags=["Seller Wallet"])


async def _get_direct_child(db: AsyncSession, *, current_user_id: int, child_username: str) -> User:
    res = await db.execute(select(User).where(User.username == child_username))
    child = res.scalar_one_or_none()
    if child is None:
        raise HTTPException(status_code=404, detail="Child seller not found.")

    if int(child.parent_id or 0) != int(current_user_id):
        raise HTTPException(status_code=403, detail="Not allowed. Only direct child is permitted.")

    return child


@router.get("/balance/my", response_model=BalanceOut)
async def seller_my_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BalanceOut:
    data = await get_current_balance(db, user_id=int(current_user.id))
    data["username"] = current_user.username or ""
    return BalanceOut(**data)


@router.get("/balance/child", response_model=BalanceOut)
async def seller_child_balance(
    child_username: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BalanceOut:
    child = await _get_direct_child(db, current_user_id=int(current_user.id), child_username=child_username)
    data = await get_current_balance(db, user_id=int(child.id))
    data["username"] = child.username or child_username
    return BalanceOut(**data)


@router.get("/history/my", response_model=BalanceHistoryListOut)
async def seller_my_balance_history(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    entry_kind: Optional[str] = None,
    tx_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BalanceHistoryListOut:
    try:
        data = await list_balance_history(
            db,
            user_id=int(current_user.id),
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


@router.get("/history/child", response_model=BalanceHistoryListOut)
async def seller_child_balance_history(
    child_username: str = Query(...),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    entry_kind: Optional[str] = None,
    tx_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BalanceHistoryListOut:
    child = await _get_direct_child(db, current_user_id=int(current_user.id), child_username=child_username)

    try:
        data = await list_balance_history(
            db,
            user_id=int(child.id),
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


@router.get("/tx/my/{tx_id}", response_model=TxDetailsOut)
async def seller_my_tx_details(
    tx_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TxDetailsOut:
    data = await get_tx_details_for_user(db, user_id=int(current_user.id), tx_id=tx_id)
    return TxDetailsOut(user_id=int(current_user.id), username=current_user.username or "", tx_id=tx_id, rows=data["rows"])


@router.get("/tx/child/{tx_id}", response_model=TxDetailsOut)
async def seller_child_tx_details(
    tx_id: str,
    child_username: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TxDetailsOut:
    child = await _get_direct_child(db, current_user_id=int(current_user.id), child_username=child_username)
    data = await get_tx_details_for_user(db, user_id=int(child.id), tx_id=tx_id)
    return TxDetailsOut(user_id=int(child.id), username=child.username or child_username, tx_id=tx_id, rows=data["rows"])
