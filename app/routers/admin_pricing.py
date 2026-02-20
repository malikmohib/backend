from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas.pricing import (
    AdminBasePriceOut,
    AdminBasePriceUpsertIn,
    AdminEdgePriceUpsertIn,
    EdgePriceOut,
)
from app.services.pricing import (
    admin_get_base_price,
    admin_list_base_prices,
    admin_upsert_base_price,
    upsert_edge_price_admin_override,
)

router = APIRouter(prefix="/admin/prices", tags=["Admin Pricing"])


@router.put("/base", response_model=AdminBasePriceOut, dependencies=[Depends(require_admin)])
async def upsert_admin_base_price(
    payload: AdminBasePriceUpsertIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = await admin_upsert_base_price(
        db,
        admin_user_id=current_user.id,
        plan_id=payload.plan_id,
        base_price_cents=payload.base_price_cents,
        currency=payload.currency,
    )
    return row


@router.get("/base", response_model=list[AdminBasePriceOut], dependencies=[Depends(require_admin)])
async def list_admin_base_prices(
    db: AsyncSession = Depends(get_db),
):
    return await admin_list_base_prices(db)


@router.get("/base/{plan_id}", response_model=AdminBasePriceOut, dependencies=[Depends(require_admin)])
async def get_admin_base_price(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await admin_get_base_price(db, plan_id)


@router.put("/edge-override", response_model=EdgePriceOut, dependencies=[Depends(require_admin)])
async def upsert_admin_edge_override(
    payload: AdminEdgePriceUpsertIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = await upsert_edge_price_admin_override(
        db,
        admin_user_id=current_user.id,
        parent_user_id=payload.parent_user_id,
        child_user_id=payload.child_user_id,
        plan_id=payload.plan_id,
        price_cents=payload.price_cents,
        currency=payload.currency,
    )
    return row
