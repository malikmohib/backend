# app/routers/seller_order_report.py

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.user import User
from app.schemas.order_report import OrderReportOut

# ✅ SELLER-ONLY service (does not affect admin)
from app.services.seller_order_report import get_seller_order_report_json_scoped_by_path



router = APIRouter(prefix="/sellers/report", tags=["Seller Reports"])


async def _get_direct_child_by_username(
    db: AsyncSession, *, current_user_id: int, username: str
) -> User:
    res = await db.execute(select(User).where(User.username == username))
    child = res.scalar_one_or_none()
    if child is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if int(child.parent_id or 0) != int(current_user_id):
        raise HTTPException(status_code=403, detail="Not allowed. Only direct child is permitted.")

    if not child.path:
        raise HTTPException(status_code=400, detail="Child user has no path.")

    return child


@router.get("", response_model=OrderReportOut)
async def seller_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_seller),
    # same UX as admin: username picker, but only direct children allowed
    username: str = Query(..., min_length=1),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=100000),
    offset: int = Query(default=0, ge=0),
) -> OrderReportOut:
    if not current_user.path:
        raise HTTPException(status_code=400, detail="Current user has no path.")

    seller_id = int(current_user.id)
    seller_username = current_user.username or ""
    seller_path = str(current_user.path)

    uname = username.strip()

    # ✅ self report (bucket=self)
    if uname == seller_username:
        scope_path = seller_path
        bucket_user_id = seller_id
        bucket_username = seller_username
    else:
        # ✅ direct child report: includes grandchildren but bucketed to child
        child = await _get_direct_child_by_username(db, current_user_id=seller_id, username=uname)
        scope_path = str(child.path)
        bucket_user_id = int(child.id)
        bucket_username = child.username or ""

    # ✅ call seller-only service
    return await get_seller_order_report_json_scoped_by_path(
        db,
        bucket_user_id=bucket_user_id,
        bucket_username=bucket_username,
        scope_path=scope_path,
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        limit=limit,
        offset=offset,
    )