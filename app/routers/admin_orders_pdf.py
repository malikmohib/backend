from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.services.orders_pdf import OrdersPdfError, generate_orders_items_pdf_by_username


router = APIRouter(prefix="/admin/reports", tags=["Admin Reports"])


@router.get("/seller-orders.pdf")
async def admin_seller_orders_pdf(
    username: str = Query(...),
    plan_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        pdf_bytes, user_id = await generate_orders_items_pdf_by_username(
            db,
            username=username,
            plan_id=plan_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        filename = f"seller_orders_{username}_{user_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except OrdersPdfError as e:
        raise HTTPException(status_code=400, detail=str(e))
