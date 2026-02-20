from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.me import MeOut
from app.services.wallet import get_balance

router = APIRouter(tags=["Me"])


@router.get("/me", response_model=MeOut)
async def me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MeOut:
    wa = await get_balance(db, int(current_user.id))
    return MeOut(
        id=int(current_user.id),
        username=current_user.username,
        role=current_user.role,
        full_name=current_user.full_name,
        email=current_user.email,
        phone=current_user.phone,
        country=current_user.country,
        is_active=bool(current_user.is_active),
        balance_cents=int(wa.balance_cents),
        currency=wa.currency,
    )
