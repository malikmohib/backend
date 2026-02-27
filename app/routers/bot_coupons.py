from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.db import get_db
from app.models.coupon import Coupon
from app.integrations.geek_api_client import GeekApiClient

router = APIRouter(prefix="/bot/coupons", tags=["Bot Coupons"])


@router.get("/{coupon_code}")
async def get_coupon_info(
    coupon_code: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Coupon).where(Coupon.code == coupon_code)
    )
    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    return {
        "status": coupon.status,
        "category": coupon.coupon_category_snapshot,
    }


@router.post("/{coupon_code}/issue")
async def issue_coupon(
    coupon_code: str,
    udid: str,
    note: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Coupon).where(Coupon.code == coupon_code)
    )
    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if coupon.status != "new":
        raise HTTPException(status_code=400, detail="Already used")

    snapshot = coupon.coupon_category_snapshot
    client = GeekApiClient()

    response = await client.issue_device(
        udid=udid,
        issue_mode=snapshot["issue_mode"],
        pool_type=snapshot["pool_type"],
        warranty=snapshot["warranty"],
        note=note,
    )

    coupon.status = "used"
    await db.commit()

    return response