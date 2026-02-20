from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.order_report import OrderReportOut
from app.services.order_report import OrderReportError, get_order_report_json


router = APIRouter(prefix="/reports/orders", tags=["Reports"])


async def _get_direct_child(db: AsyncSession, *, current_user_id: int, child_username: str) -> User:
    res = await db.execute(select(User).where(User.username == child_username))
    child = res.scalar_one_or_none()
    if child is None:
        raise HTTPException(status_code=404, detail="Child seller not found.")

    if int(child.parent_id or 0) != int(current_user_id):
        raise HTTPException(status_code=403, detail="Not allowed. Only direct child is permitted.")

    return child


@router.get("/my", response_model=OrderReportOut)
async def my_orders_report(
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderReportOut:
    try:
        data = await get_order_report_json(
            db,
            buyer_user_id=int(current_user.id),
            username=current_user.username or f"user_{current_user.id}",
            plan_id=plan_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return OrderReportOut(**data)
    except OrderReportError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/child", response_model=OrderReportOut)
async def child_orders_report(
    child_username: str = Query(...),
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderReportOut:
    child = await _get_direct_child(db, current_user_id=int(current_user.id), child_username=child_username)

    try:
        data = await get_order_report_json(
            db,
            buyer_user_id=int(child.id),
            username=child.username or child_username,
            plan_id=plan_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return OrderReportOut(**data)
    except OrderReportError as e:
        raise HTTPException(status_code=400, detail=str(e))
