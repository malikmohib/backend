from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.services.reports import (
    ReportError,
    generate_coupons_history_pdf,
    generate_coupon_trace_pdf,
)

router = APIRouter(prefix="/admin/reports", tags=["Admin Reports"])


@router.get("/coupons/history.pdf")
async def admin_coupons_history_pdf(
    generated_by_user_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    used_by_user_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=2000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    try:
        pdf_bytes = await generate_coupons_history_pdf(
            db,
            current_admin=current_admin,
            generated_by_user_id=generated_by_user_id,
            owner_user_id=owner_user_id,
            used_by_user_id=used_by_user_id,
            plan_id=plan_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        filename = "coupons_history.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except ReportError as e:
        # ReportError now includes permission errors too
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/coupons/{coupon_code}/trace.pdf")
async def admin_coupon_trace_pdf(
    coupon_code: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    try:
        pdf_bytes = await generate_coupon_trace_pdf(
            db,
            coupon_code=coupon_code,
            current_admin=current_admin,
        )
        safe_code = coupon_code.replace("/", "_")
        filename = f"coupon_trace_{safe_code}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except ReportError as e:
        # keep 404 semantics for "not found"
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
