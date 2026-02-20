from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import AdminPlanBasePrice, SellerEdgePlanPrice
from app.models.user import User
from app.services.seller_plans import seller_has_plan_enabled  # ✅ ADDED


@dataclass
class ParentCost:
    parent_cost_cents: int
    currency: str
    source: str  # "admin_base_price" | "edge_price"


# -------------------------
# Helpers
# -------------------------

async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


async def _ensure_child_is_direct(db: AsyncSession, parent_user_id: int, child_user_id: int) -> None:
    # direct relationship required for seller-managed edges
    res = await db.execute(
        select(User.id).where(and_(User.id == child_user_id, User.parent_id == parent_user_id))
    )
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="child_user_id is not a direct child of current user")


async def determine_parent_cost(db: AsyncSession, parent_user_id: int, plan_id: int) -> ParentCost:
    parent = await _get_user_or_404(db, parent_user_id)

    if parent.role == "admin":
        res = await db.execute(select(AdminPlanBasePrice).where(AdminPlanBasePrice.plan_id == plan_id))
        base = res.scalar_one_or_none()
        if not base:
            raise HTTPException(status_code=400, detail="Admin base price not set for this plan_id")
        return ParentCost(parent_cost_cents=base.base_price_cents, currency=base.currency, source="admin_base_price")

    # seller/agent/etc: cost comes from edge (parent.parent -> parent)
    if parent.parent_id is None:
        raise HTTPException(status_code=400, detail="Parent has no parent_id; cannot determine parent cost")

    res = await db.execute(
        select(SellerEdgePlanPrice).where(
            and_(
                SellerEdgePlanPrice.parent_user_id == parent.parent_id,
                SellerEdgePlanPrice.child_user_id == parent.id,
                SellerEdgePlanPrice.plan_id == plan_id,
            )
        )
    )
    edge = res.scalar_one_or_none()
    if not edge:
        raise HTTPException(
            status_code=400,
            detail="Parent cost not found: missing edge price for (parent.parent -> parent) for this plan_id",
        )

    return ParentCost(parent_cost_cents=edge.price_cents, currency=edge.currency, source="edge_price")


# -------------------------
# Admin: base prices
# -------------------------

async def admin_upsert_base_price(
    db: AsyncSession,
    *,
    admin_user_id: int,
    plan_id: int,
    base_price_cents: int,
    currency: str,
) -> AdminPlanBasePrice:
    res = await db.execute(select(AdminPlanBasePrice).where(AdminPlanBasePrice.plan_id == plan_id))
    row = res.scalar_one_or_none()

    if row:
        row.base_price_cents = base_price_cents
        row.currency = currency
        row.updated_by_user_id = admin_user_id
    else:
        row = AdminPlanBasePrice(
            plan_id=plan_id,
            base_price_cents=base_price_cents,
            currency=currency,
            updated_by_user_id=admin_user_id,
        )
        db.add(row)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid plan_id or DB constraint failed")

    await db.refresh(row)
    return row


async def admin_list_base_prices(db: AsyncSession) -> List[AdminPlanBasePrice]:
    res = await db.execute(select(AdminPlanBasePrice).order_by(AdminPlanBasePrice.plan_id.asc()))
    return list(res.scalars().all())


async def admin_get_base_price(db: AsyncSession, plan_id: int) -> AdminPlanBasePrice:
    res = await db.execute(select(AdminPlanBasePrice).where(AdminPlanBasePrice.plan_id == plan_id))
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Base price not found for plan_id")
    return row


# -------------------------
# Edge prices (seller/admin)
# -------------------------

async def upsert_edge_price_seller(
    db: AsyncSession,
    *,
    current_user_id: int,
    child_user_id: int,
    plan_id: int,
    price_cents: int,
    currency: str,
) -> SellerEdgePlanPrice:
    # Must be direct child
    await _ensure_child_is_direct(db, current_user_id, child_user_id)

    # ✅ Enforce: seller can only pass down plans they have
    # Seller "has" a plan if there exists an incoming edge price (parent -> seller) for that plan.
    has_plan = await seller_has_plan_enabled(db, seller_user_id=current_user_id, plan_id=plan_id)
    if not has_plan:
        raise HTTPException(
            status_code=400,
            detail="Plan not enabled for this seller. Admin must set (parent -> seller) price first.",
        )

    # Enforce margin rule: price >= parent cost
    parent_cost = await determine_parent_cost(db, current_user_id, plan_id)
    if currency != parent_cost.currency:
        raise HTTPException(
            status_code=400,
            detail=f"Currency mismatch. Parent cost currency is {parent_cost.currency}",
        )
    if price_cents < parent_cost.parent_cost_cents:
        raise HTTPException(
            status_code=400,
            detail=f"Price too low. Must be >= parent cost ({parent_cost.parent_cost_cents} {parent_cost.currency})",
        )

    res = await db.execute(
        select(SellerEdgePlanPrice).where(
            and_(
                SellerEdgePlanPrice.parent_user_id == current_user_id,
                SellerEdgePlanPrice.child_user_id == child_user_id,
                SellerEdgePlanPrice.plan_id == plan_id,
            )
        )
    )
    row = res.scalar_one_or_none()

    if row:
        # If admin override exists, sellers cannot change it.
        if row.is_admin_override:
            raise HTTPException(status_code=403, detail="This edge price is admin overridden and cannot be changed")
        row.price_cents = price_cents
        row.currency = currency
        row.updated_by_user_id = current_user_id
    else:
        row = SellerEdgePlanPrice(
            parent_user_id=current_user_id,
            child_user_id=child_user_id,
            plan_id=plan_id,
            price_cents=price_cents,
            currency=currency,
            is_admin_override=False,
            updated_by_user_id=current_user_id,
        )
        db.add(row)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="DB constraint failed (invalid user_id/plan_id?)")

    await db.refresh(row)
    return row


async def upsert_edge_price_admin_override(
    db: AsyncSession,
    *,
    admin_user_id: int,
    parent_user_id: int,
    child_user_id: int,
    plan_id: int,
    price_cents: int,
    currency: str,
) -> SellerEdgePlanPrice:
    # Admin can override ANY edge, and bypass margin rule by definition.
    # But we still require the edge to be a real direct parent->child in the tree.
    await _ensure_child_is_direct(db, parent_user_id, child_user_id)

    res = await db.execute(
        select(SellerEdgePlanPrice).where(
            and_(
                SellerEdgePlanPrice.parent_user_id == parent_user_id,
                SellerEdgePlanPrice.child_user_id == child_user_id,
                SellerEdgePlanPrice.plan_id == plan_id,
            )
        )
    )
    row = res.scalar_one_or_none()

    if row:
        row.price_cents = price_cents
        row.currency = currency
        row.is_admin_override = True
        row.updated_by_user_id = admin_user_id
    else:
        row = SellerEdgePlanPrice(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
            plan_id=plan_id,
            price_cents=price_cents,
            currency=currency,
            is_admin_override=True,
            updated_by_user_id=admin_user_id,
        )
        db.add(row)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="DB constraint failed (invalid user_id/plan_id?)")

    await db.refresh(row)
    return row


async def list_edges_for_parent(
    db: AsyncSession,
    *,
    parent_user_id: int,
    plan_id: Optional[int] = None,
) -> List[SellerEdgePlanPrice]:
    stmt = select(SellerEdgePlanPrice).where(SellerEdgePlanPrice.parent_user_id == parent_user_id)
    if plan_id is not None:
        stmt = stmt.where(SellerEdgePlanPrice.plan_id == plan_id)
    stmt = stmt.order_by(SellerEdgePlanPrice.child_user_id.asc(), SellerEdgePlanPrice.plan_id.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def list_edges_within_subtree(
    db: AsyncSession,
    *,
    root_user_id: int,
    plan_id: Optional[int] = None,
) -> List[SellerEdgePlanPrice]:
    # We want edges where parent_user is inside root subtree.
    # Using ltree: parent.path <@ root.path (parent is descendant of root)
    root = await _get_user_or_404(db, root_user_id)

    # SQLAlchemy + custom ltree type: safest is raw ltree operator via text()
    # Join seller_edge_plan_prices -> users (parent)
    sql = """
    SELECT ep.*
    FROM public.seller_edge_plan_prices ep
    JOIN public.users u_parent ON u_parent.id = ep.parent_user_id
    WHERE u_parent.path <@ :root_path
    """
    params = {"root_path": str(root.path)}
    if plan_id is not None:
        sql += " AND ep.plan_id = :plan_id"
        params["plan_id"] = plan_id
    sql += " ORDER BY ep.parent_user_id, ep.child_user_id, ep.plan_id"

    res = await db.execute(text(sql), params)
    rows = res.mappings().all()

    # Convert mappings -> ORM objects (simple manual hydration)
    out: List[SellerEdgePlanPrice] = []
    for r in rows:
        obj = SellerEdgePlanPrice(**dict(r))
        out.append(obj)
    return out
