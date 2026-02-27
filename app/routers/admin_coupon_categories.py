from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.db import get_db
from app.models.coupon_category import CouponCategory
from app.models.plan import Plan
from app.models.coupon import Coupon
from app.schemas.coupon_categories import (
    CouponCategoryCreate,
    CouponCategoryUpdate,
    CouponCategoryOut,
)

router = APIRouter(prefix="/admin/coupon-categories", tags=["Admin Coupon Categories"])


@router.post("", response_model=CouponCategoryOut)
async def create_category(
    data: CouponCategoryCreate,
    db: AsyncSession = Depends(get_db),
):
    cat = CouponCategory(**data.dict())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.get("", response_model=list[CouponCategoryOut])
async def list_categories(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CouponCategory))
    return result.scalars().all()


@router.patch("/{category_id}", response_model=CouponCategoryOut)
async def update_category(
    category_id: int,
    data: CouponCategoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CouponCategory).where(CouponCategory.id == category_id)
    )
    cat = result.scalar_one_or_none()

    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(cat, field, value)

    await db.commit()
    await db.refresh(cat)
    return cat


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
):
    # Prevent deletion if referenced
    plan_check = await db.execute(
        select(Plan).where(Plan.coupon_category_id == category_id)
    )
    if plan_check.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Category is used by plans",
        )

    coupon_check = await db.execute(
        select(Coupon).where(Coupon.coupon_category_id == category_id)
    )
    if coupon_check.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Category is used by coupons",
        )

    await db.execute(
        delete(CouponCategory).where(CouponCategory.id == category_id)
    )
    await db.commit()

    return {"detail": "Deleted"}