from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.services.reports_pdf import ReportError, generate_seller_keys_pdf_by_username


router = APIRouter(prefix="/admin/reports", tags=["Admin Reports"])


@router.get("/seller-keys.pdf")
async def admin_seller_keys_pdf(
    username: str = Query(...),
    scope: str = Query(default="generated"),  # generated | owned | used
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        pdf_bytes, user_id = await generate_seller_keys_pdf_by_username(
            db,
            username=username,
            scope=scope,
            plan_id=plan_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        filename = f"seller_keys_{username}_{user_id}_{scope}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except ReportError as e:
        raise HTTPException(status_code=400, detail=str(e))
