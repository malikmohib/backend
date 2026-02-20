# app/routers/admin_coupons.py
from __future__ import annotations
from fastapi import HTTPException
from app.models.plan import Plan
from app.schemas.coupons import AdminCouponPlanOut
from app.schemas.coupons import AdminCouponReserveRequest, AdminCouponFailRequest
from app.services.coupons import admin_reserve_coupon, admin_mark_coupon_failed

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.coupon import Coupon
from app.schemas.coupons import (
    AdminCouponGenerateRequest,
    AdminCouponResponse,
    AdminCouponUnreserveRequest,
    AdminCouponVoidRequest,
)
from app.services.coupons import (
    admin_generate_coupons,
    admin_unreserve_coupon,
    admin_void_coupon,
)

router = APIRouter(prefix="/admin/coupons", tags=["Admin - Coupons"])


@router.post("", response_model=list[AdminCouponResponse])
async def generate_coupons(
    body: AdminCouponGenerateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    # ✅ Owner is always the authenticated user.
    # ✅ Prevents generating coupons under someone else.
    return await admin_generate_coupons(
        db,
        plan_id=body.plan_id,
        count=body.count,
        created_by_user_id=admin_user.id,
        owner_user_id=admin_user.id,
        notes=body.notes,
    )



@router.get("", response_model=list[AdminCouponResponse])
async def list_coupons(
    status: str | None = Query(default=None),
    plan_id: int | None = Query(default=None),
    owner_user_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    stmt = select(Coupon).order_by(Coupon.created_at.desc())

    if status:
        stmt = stmt.where(Coupon.status == status)
    if plan_id:
        stmt = stmt.where(Coupon.plan_id == plan_id)
    if owner_user_id:
        stmt = stmt.where(Coupon.owner_user_id == owner_user_id)

    res = await db.execute(stmt.limit(500))
    return res.scalars().all()


@router.post("/{coupon_code}/unreserve", response_model=AdminCouponResponse)
async def unreserve_coupon(
    coupon_code: str,
    body: AdminCouponUnreserveRequest,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    return await admin_unreserve_coupon(
    db,
    coupon_code=coupon_code,
    reason=body.reason,
    actor_user_id=admin_user.id,
)



@router.post("/{coupon_code}/void", response_model=AdminCouponResponse)
async def void_coupon(
    coupon_code: str,
    body: AdminCouponVoidRequest,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    return await admin_void_coupon(
    db,
    coupon_code=coupon_code,
    reason=body.reason,
    actor_user_id=admin_user.id,
)

@router.post("/{coupon_code}/reserve", response_model=AdminCouponResponse)
async def reserve_coupon(
    coupon_code: str,
    body: AdminCouponReserveRequest,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    return await admin_reserve_coupon(
        db,
        coupon_code=coupon_code,
        udid=body.udid,
        notes=body.notes,
        actor_user_id=admin_user.id,
    )


@router.post("/{coupon_code}/fail", response_model=AdminCouponResponse)
async def fail_coupon(
    coupon_code: str,
    body: AdminCouponFailRequest,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    return await admin_mark_coupon_failed(
        db,
        coupon_code=coupon_code,
        reason=body.reason,
        step=body.step,
        actor_user_id=admin_user.id,
    )



@router.get("/{coupon_code}", response_model=AdminCouponResponse)
async def get_coupon(
    coupon_code: str,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    coupon = await db.get(Coupon, coupon_code)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return coupon


@router.get("/{coupon_code}/plan", response_model=AdminCouponPlanOut)
async def get_coupon_plan(
    coupon_code: str,
    db: AsyncSession = Depends(get_db),
    admin_user=Depends(require_admin),
):
    coupon = await db.get(Coupon, coupon_code)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    plan = await db.get(Plan, coupon.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found for coupon")

    return AdminCouponPlanOut(
        plan_id=plan.id,
        plan_code=plan.code,
        plan_title=plan.title,
        provider_api_params=plan.provider_api_params or {},
    )
