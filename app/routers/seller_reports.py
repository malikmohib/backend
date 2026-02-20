from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.reports_pdf import ReportError, generate_user_keys_pdf


router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/my-keys.pdf")
async def my_keys_pdf(
    scope: str = Query(default="generated"),  # generated | owned | used
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pdf_bytes = await generate_user_keys_pdf(
            db,
            user_id=int(current_user.id),
            username=current_user.username or f"user_{current_user.id}",
            scope=scope,
            plan_id=plan_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        filename = f"my_keys_{scope}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except ReportError as e:
        raise HTTPException(status_code=400, detail=str(e))
