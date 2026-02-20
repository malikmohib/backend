# app/routers/admin_plans.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.plan import Plan
from app.schemas.plans import PlanCreate, PlanOut, PlanUpdate

router = APIRouter(prefix="/admin/plans", tags=["Admin - Plans"])


@router.post("", response_model=PlanOut)
async def create_plan(
    body: PlanCreate,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    plan = Plan(
        category=body.category,
        code=body.code,
        title=body.title,
        warranty_days=body.warranty_days,
        is_instant=body.is_instant,
        is_active=body.is_active,
        provider_api_params=body.provider_api_params or {},
    )

    try:
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
        return plan
    except Exception:
        await db.rollback()
        raise


@router.get("", response_model=list[PlanOut])
async def list_plans(
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    stmt = select(Plan).order_by(Plan.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/{plan_id}", response_model=PlanOut)
async def get_plan(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    plan = await db.get(Plan, plan_id)
    if not plan:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.patch("/{plan_id}", response_model=PlanOut)
async def update_plan(
    plan_id: int,
    body: PlanUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    plan = await db.get(Plan, plan_id)
    if not plan:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Plan not found")

    if body.category is not None:
        plan.category = body.category
    if body.code is not None:
        plan.code = body.code
    if body.title is not None:
        plan.title = body.title
    if body.warranty_days is not None:
        plan.warranty_days = body.warranty_days
    if body.is_instant is not None:
        plan.is_instant = body.is_instant
    if body.is_active is not None:
        plan.is_active = body.is_active
    if body.provider_api_params is not None:
        plan.provider_api_params = body.provider_api_params or {}

    try:
        await db.commit()
        await db.refresh(plan)
        return plan
    except Exception:
        await db.rollback()
        raise
