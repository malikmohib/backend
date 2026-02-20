from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.schemas.pricing import EdgePriceOut, ParentCostOut, SellerEdgePriceUpsertIn
from app.services.pricing import (
    determine_parent_cost,
    list_edges_for_parent,
    list_edges_within_subtree,
    upsert_edge_price_seller,
)

router = APIRouter(prefix="/sellers/prices", tags=["Seller Pricing"])


@router.get("/my-cost/{plan_id}", response_model=ParentCostOut)
async def get_my_parent_cost(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cost = await determine_parent_cost(db, current_user.id, plan_id)
    return {
        "parent_user_id": current_user.id,
        "plan_id": plan_id,
        "parent_cost_cents": cost.parent_cost_cents,
        "currency": cost.currency,
        "source": cost.source,
    }


@router.put("/edge", response_model=EdgePriceOut)
async def upsert_price_for_direct_child(
    payload: SellerEdgePriceUpsertIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = await upsert_edge_price_seller(
        db,
        current_user_id=current_user.id,
        child_user_id=payload.child_user_id,
        plan_id=payload.plan_id,
        price_cents=payload.price_cents,
        currency=payload.currency,
    )
    return row


@router.get("/direct-children", response_model=list[EdgePriceOut])
async def list_prices_for_my_direct_children(
    plan_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await list_edges_for_parent(db, parent_user_id=current_user.id, plan_id=plan_id)


@router.get("/subtree", response_model=list[EdgePriceOut])
async def list_prices_within_my_subtree(
    plan_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await list_edges_within_subtree(db, root_user_id=current_user.id, plan_id=plan_id)

