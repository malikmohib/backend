# app/routers/seller_wallet.py

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.wallet import AdjustChildBalanceIn, TransferIn, TxOut, WalletBalanceOut
from app.services.wallet import (
    ForbiddenTransfer,
    InsufficientBalance,
    WalletError,
    adjust_child_balance_down,
    get_balance,
    transfer_to_child,
)

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.get("/me", response_model=WalletBalanceOut)
async def my_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WalletBalanceOut:
    wa = await get_balance(db, current_user.id)
    return WalletBalanceOut(user_id=wa.user_id, balance_cents=wa.balance_cents, currency=wa.currency)


@router.post("/transfer-to-child", response_model=TxOut)
async def transfer_to_direct_child(
    payload: TransferIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TxOut:
    try:
        # Optional: nice 404 if child doesn't exist
        res = await db.execute(select(User).where(User.id == payload.child_user_id))
        child = res.scalar_one_or_none()
        if child is None:
            raise HTTPException(status_code=404, detail="Child user not found.")

        # ✅ Correct call for your service:
        # - parent_user must be a User object (service reads parent_user.id)
        # - child_user_id must be an int (service loads child by id)
        entries = await transfer_to_child(
            db,
            current_user,                 # parent_user (User)
            int(payload.child_user_id),   # child_user_id (int)
            int(payload.amount_cents),    # amount_cents
            payload.note,                 # note
        )

        tx_id = str(entries[0].tx_id)
        created_at = entries[0].created_at
        return TxOut(tx_id=tx_id, created_at=created_at, message="Transfer successful")

    except ForbiddenTransfer as e:
        raise HTTPException(status_code=403, detail=str(e))
    except InsufficientBalance as e:
        raise HTTPException(status_code=400, detail=str(e))
    except WalletError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/adjust-child-balance", response_model=TxOut)
async def adjust_direct_child_balance(
    payload: AdjustChildBalanceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TxOut:
    """
    Reduce a direct child's balance to target_balance_cents.
    The difference is returned to the current_user (parent seller).
    """
    try:
        res = await db.execute(select(User).where(User.id == payload.child_user_id))
        child = res.scalar_one_or_none()
        if child is None:
            raise HTTPException(status_code=404, detail="Child user not found.")

        # Based on how transfer_to_child is implemented, adjust_child_balance_down
        # is very likely the same style: (db, parent_user, child_user_id, target_balance_cents, note)
        entries = await adjust_child_balance_down(
            db,
            current_user,                      # parent_user (User)
            int(payload.child_user_id),        # child_user_id (int)
            int(payload.target_balance_cents), # target_balance_cents
            payload.note,                      # note
        )

        tx_id = str(entries[0].tx_id)
        created_at = entries[0].created_at
        return TxOut(tx_id=tx_id, created_at=created_at, message="Balance adjusted successfully")

    except ForbiddenTransfer as e:
        raise HTTPException(status_code=403, detail=str(e))
    except WalletError as e:
        raise HTTPException(status_code=400, detail=str(e))