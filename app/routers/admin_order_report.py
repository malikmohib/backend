from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.schemas.order_report import OrderReportOut
from app.services.order_report import OrderReportError, get_order_report_json


router = APIRouter(prefix="/admin/reports/orders", tags=["Admin Reports"])


def _is_descendant_expr(user_path_col, admin_path: str):
    # ltree: child_path <@ ancestor_path
    return user_path_col.op("<@")(admin_path)


@router.get("", response_model=OrderReportOut)
async def admin_orders_report(
    # OPTIONAL now: missing => all sellers below admin
    username: Optional[str] = Query(default=None),
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> OrderReportOut:
    if not getattr(current_admin, "path", None):
        raise HTTPException(
            status_code=400,
            detail="Current admin has no path; cannot scope subtree.",
        )

    username_norm = username.strip() if username else None

    # -----------------------------
    # CASE A: specific seller report
    # -----------------------------
    if username_norm:
        res = await db.execute(select(User).where(User.username == username_norm))
        u = res.scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail="User not found.")

        # Enforce: must be seller under this admin subtree
        if u.role != "seller":
            raise HTTPException(status_code=400, detail="username must be a seller.")
        if u.id == current_admin.id:
            raise HTTPException(status_code=403, detail="Permission denied.")

        # DB-verified subtree check
        chk = await db.execute(
            select(User.id)
            .where(User.id == u.id)
            .where(_is_descendant_expr(User.path, current_admin.path))
            .limit(1)
        )
        if chk.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=403,
                detail="Permission denied: seller not under your tree.",
            )

        try:
            data = await get_order_report_json(
                db,
                buyer_user_id=int(u.id),
                username=u.username or username_norm,
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

    # -----------------------------------
    # CASE B: ALL sellers below this admin
    # -----------------------------------
    sellers_res = await db.execute(
        select(User).where(
            User.role == "seller",
            User.id != current_admin.id,
            _is_descendant_expr(User.path, current_admin.path),
            User.is_active == True,  # noqa: E712
        )
    )
    sellers: List[User] = list(sellers_res.scalars().all())

    merged_items = []
    total = 0

    # Pull up to (offset + limit) per seller then merge & slice globally
    per_seller_limit = min(20000, offset + limit)

    for s in sellers:
        try:
            data = await get_order_report_json(
                db,
                buyer_user_id=int(s.id),
                username=s.username or "",
                plan_id=plan_id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                limit=per_seller_limit,
                offset=0,
            )
        except OrderReportError as e:
            raise HTTPException(status_code=400, detail=str(e))

        items = data.get("items") or []
        merged_items.extend(items)
        total += int(data.get("total") or 0)

    # Sort newest first if created_at exists
    try:
        merged_items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    except Exception:
        pass

    paged_items = merged_items[offset : offset + limit]

    return OrderReportOut(
        username="",
        buyer_user_id=None,
        date_from=date_from,
        date_to=date_to,
        plan_id=plan_id,
        status=status,
        items=paged_items,
        total=total,
    )
