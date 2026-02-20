from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.orders_pdf import OrdersPdfError, generate_orders_items_pdf


router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/my-orders.pdf")
async def my_orders_pdf(
    plan_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pdf_bytes = await generate_orders_items_pdf(
            db,
            buyer_user_id=int(current_user.id),
            username=current_user.username or f"user_{current_user.id}",
            plan_id=plan_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        filename = "my_orders_report.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except OrdersPdfError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/child-orders.pdf")
async def my_child_orders_pdf(
    child_username: str = Query(...),
    plan_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Seller-only export for DIRECT child seller (parent_id == current_user.id).
    """
    res = await db.execute(select(User).where(User.username == child_username))
    child = res.scalar_one_or_none()
    if child is None:
        raise HTTPException(status_code=404, detail="Child seller not found.")

    if int(child.parent_id or 0) != int(current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed. Only direct child is permitted.")

    try:
        pdf_bytes = await generate_orders_items_pdf(
            db,
            buyer_user_id=int(child.id),
            username=child.username or child_username,
            plan_id=plan_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        filename = f"child_orders_{child_username}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except OrdersPdfError as e:
        raise HTTPException(status_code=400, detail=str(e))
