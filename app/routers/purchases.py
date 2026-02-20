from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.purchases import PurchaseIn, PurchaseOut
from app.services.purchases import purchase_plan_and_distribute, PurchaseError
from app.services.wallet import InsufficientBalance


router = APIRouter(prefix="/purchases", tags=["Purchases"])


@router.post("", response_model=PurchaseOut)
async def purchase_plan(
    payload: PurchaseIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PurchaseOut:
    try:
        result = await purchase_plan_and_distribute(
            db=db,
            buyer=current_user,
            plan_id=payload.plan_id,
            quantity=payload.quantity,
            note=payload.note,
        )
        return PurchaseOut(**result)
    except InsufficientBalance as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PurchaseError as e:
        raise HTTPException(status_code=400, detail=str(e))
