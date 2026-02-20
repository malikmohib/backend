from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.orders import OrdersListOut, OrderOut
from app.services.orders import OrdersError, get_order_by_order_no, list_orders


router = APIRouter(prefix="/sellers/orders", tags=["Seller Orders"])


@router.get("/my", response_model=OrdersListOut)
async def seller_list_my_orders(
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrdersListOut:
    try:
        data = await list_orders(
            db,
            buyer_user_id=current_user.id,
            plan_id=plan_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return OrdersListOut(**data)
    except OrdersError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{order_no}", response_model=OrderOut)
async def seller_get_order(
    order_no: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    try:
        data = await get_order_by_order_no(db, order_no=order_no)
        if int(data["buyer_user_id"]) != int(current_user.id):
            raise HTTPException(status_code=403, detail="Not allowed.")
        return OrderOut(**data)
    except OrdersError as e:
        raise HTTPException(status_code=404, detail=str(e))
