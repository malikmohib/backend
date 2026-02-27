# app/routers/admin_sellers.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.plan import Plan
from app.models.pricing import SellerEdgePlanPrice
from app.models.seller_plan_price import SellerPlanPrice
from app.models.user import User
from app.models.wallet import WalletAccount

from app.schemas.admin_sellers import (
    AdminCreateSellerRequest,
    AdminSellerListResponse,
    AdminSellerOut,
    SellerPlanPriceOut,
    AdminUpdateSellerRequest,
    AdminSetSellerBalanceIn,
    AdminDeleteSellerIn,
)

from app.services.tree import create_user_under_parent
from app.services.wallet import (
    admin_set_balance_via_parent,
    admin_delete_user_return_balance_to_parent,
    get_balance,
    WalletError,
)

router = APIRouter(prefix="/admin", tags=["admin-sellers"])


async def _sync_edge_prices_full_replace(
    db: AsyncSession,
    *,
    parent_user_id: int,
    child_user_id: int,
    plan_prices: list[tuple[int, int]],  # [(plan_id, price_cents)]
    updated_by_user_id: int,
    currency: str = "USD",
) -> None:
    """
    Ensure seller_edge_plan_prices has exactly one row per (parent, child, plan)
    matching the child's assigned plan prices (full replace).
    """
    # delete all existing edges for this parent->child
    await db.execute(
        delete(SellerEdgePlanPrice).where(
            SellerEdgePlanPrice.parent_user_id == int(parent_user_id),
            SellerEdgePlanPrice.child_user_id == int(child_user_id),
        )
    )

    # insert fresh edges
    for plan_id, price_cents in plan_prices:
        db.add(
            SellerEdgePlanPrice(
                parent_user_id=int(parent_user_id),
                child_user_id=int(child_user_id),
                plan_id=int(plan_id),
                price_cents=int(price_cents),
                currency=currency,
                updated_by_user_id=int(updated_by_user_id),
                # is_admin_override defaults false in DB
            )
        )


@router.post("/sellers", response_model=AdminSellerOut)
async def admin_create_seller(
    payload: AdminCreateSellerRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    if payload.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot create admin users via this endpoint")

    parent = admin_user  # ✅ Parent is always creator (id=1 in your example)

    # Validate plan ids (exist + active)
    plan_ids = [int(p.plan_id) for p in payload.plans]
    plans_by_id: dict[int, Plan] = {}

    if plan_ids:
        res = await db.execute(select(Plan).where(Plan.id.in_(plan_ids)))
        found = res.scalars().all()
        plans_by_id = {int(p.id): p for p in found}

        missing = [pid for pid in plan_ids if pid not in plans_by_id]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown plan_id(s): {missing}")

        inactive = [pid for pid, pl in plans_by_id.items() if not bool(pl.is_active)]
        if inactive:
            raise HTTPException(status_code=400, detail=f"Inactive plan_id(s): {inactive}")

    try:
        user = await create_user_under_parent(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role.value,
            parent=parent,
            telegram_id=None,
            is_active=payload.is_active,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            country=payload.country,
        )
        await db.flush()

        # Ensure wallet exists
        db.add(WalletAccount(user_id=int(user.id), balance_cents=0, currency="USD"))
        await db.flush()

        # Parent price rule (only if parent has a record for that plan)
        if payload.plans:
            parent_prices_res = await db.execute(
                select(SellerPlanPrice).where(
                    SellerPlanPrice.seller_id == int(parent.id),
                    SellerPlanPrice.plan_id.in_(plan_ids),
                )
            )
            parent_prices = {int(r.plan_id): int(r.price_cents) for r in parent_prices_res.scalars().all()}

            for pp in payload.plans:
                pid = int(pp.plan_id)
                if pid in parent_prices and int(pp.price_cents) < parent_prices[pid]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Plan {pid} price_cents must be >= parent price ({parent_prices[pid]})",
                    )

            # Insert child plan prices
            for pp in payload.plans:
                db.add(
                    SellerPlanPrice(
                        seller_id=int(user.id),
                        plan_id=int(pp.plan_id),
                        price_cents=int(pp.price_cents),
                        currency="USD",
                    )
                )

            # ✅ CRITICAL FIX: create edge rows parent->child for the same plans
            await _sync_edge_prices_full_replace(
                db,
                parent_user_id=int(parent.id),
                child_user_id=int(user.id),
                plan_prices=[(int(pp.plan_id), int(pp.price_cents)) for pp in payload.plans],
                updated_by_user_id=int(admin_user.id),
                currency="USD",
            )

        await db.commit()
        await db.refresh(user)

        out_plans: list[SellerPlanPriceOut] = []
        for pp in payload.plans:
            pl = plans_by_id.get(int(pp.plan_id))
            out_plans.append(
                SellerPlanPriceOut(
                    plan_id=int(pp.plan_id),
                    title=pl.title if pl else "",
                    price_cents=int(pp.price_cents),
                )
            )

        return AdminSellerOut(
            id=int(user.id),
            username=user.username,
            role=user.role,
            parent_id=int(user.parent_id) if user.parent_id is not None else None,
            parent_username=parent.username,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            country=user.country,
            is_active=bool(user.is_active),
            created_at=user.created_at,
            balance_cents=0,
            currency="USD",
            plans=out_plans,
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


@router.get("/sellers", response_model=AdminSellerListResponse)
async def admin_list_sellers(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    parent_alias = User.__table__.alias("parent_user")

    stmt = (
        select(
            User.id,
            User.username,
            User.role,
            User.parent_id,
            parent_alias.c.username.label("parent_username"),
            User.full_name,
            User.email,
            User.phone,
            User.country,
            User.is_active,
            User.created_at,
            WalletAccount.balance_cents,
            WalletAccount.currency,
        )
        .select_from(User)
        .outerjoin(WalletAccount, WalletAccount.user_id == User.id)
        .outerjoin(parent_alias, parent_alias.c.id == User.parent_id)
        .order_by(User.created_at.desc())
    )

    res = await db.execute(stmt)
    rows = res.all()

    user_ids = [int(r.id) for r in rows]
    prices_by_user: dict[int, list[SellerPlanPriceOut]] = {uid: [] for uid in user_ids}

    if user_ids:
        price_rows = await db.execute(
            select(SellerPlanPrice, Plan)
            .join(Plan, Plan.id == SellerPlanPrice.plan_id)
            .where(SellerPlanPrice.seller_id.in_(user_ids))
        )
        for spp, pl in price_rows.all():
            prices_by_user[int(spp.seller_id)].append(
                SellerPlanPriceOut(
                    plan_id=int(spp.plan_id),
                    title=pl.title,
                    price_cents=int(spp.price_cents),
                )
            )

    items: list[AdminSellerOut] = []
    for r in rows:
        items.append(
            AdminSellerOut(
                id=int(r.id),
                username=r.username,
                role=r.role,
                parent_id=int(r.parent_id) if r.parent_id is not None else None,
                parent_username=r.parent_username,
                full_name=r.full_name,
                email=r.email,
                phone=r.phone,
                country=r.country,
                is_active=bool(r.is_active),
                created_at=r.created_at,
                balance_cents=int(r.balance_cents) if r.balance_cents is not None else 0,
                currency=r.currency or "USD",
                plans=prices_by_user.get(int(r.id), []),
            )
        )

    return {"items": items}


@router.patch("/sellers/{seller_id}", response_model=AdminSellerOut)
async def admin_update_seller(
    seller_id: int,
    payload: AdminUpdateSellerRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    res = await db.execute(select(User).where(User.id == int(seller_id)))
    seller = res.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    if payload.role is not None and payload.role.value == "admin":
        raise HTTPException(status_code=400, detail="Cannot set role to admin via this endpoint")

    try:
        # scalar fields
        if payload.full_name is not None:
            seller.full_name = payload.full_name
        if payload.email is not None:
            seller.email = payload.email
        if payload.phone is not None:
            seller.phone = payload.phone
        if payload.country is not None:
            seller.country = payload.country
        if payload.is_active is not None:
            seller.is_active = payload.is_active
        if payload.role is not None:
            seller.role = payload.role.value

        # plans: full replace if provided
        if payload.plans is not None:
            plan_ids = [int(p.plan_id) for p in payload.plans]
            if len(plan_ids) != len(set(plan_ids)):
                raise HTTPException(status_code=400, detail="Duplicate plan_id in plans payload")

            # validate plans exist + active
            plans_by_id: dict[int, Plan] = {}
            if plan_ids:
                res_plans = await db.execute(select(Plan).where(Plan.id.in_(plan_ids)))
                found = res_plans.scalars().all()
                plans_by_id = {int(p.id): p for p in found}

                missing = [pid for pid in plan_ids if pid not in plans_by_id]
                if missing:
                    raise HTTPException(status_code=400, detail=f"Unknown plan_id(s): {missing}")

                inactive = [pid for pid, pl in plans_by_id.items() if not bool(pl.is_active)]
                if inactive:
                    raise HTTPException(status_code=400, detail=f"Inactive plan_id(s): {inactive}")

            parent_id = int(seller.parent_id) if seller.parent_id is not None else int(admin_user.id)

            # parent price rule (only if parent has a record)
            if plan_ids:
                parent_prices_res = await db.execute(
                    select(SellerPlanPrice).where(
                        SellerPlanPrice.seller_id == int(parent_id),
                        SellerPlanPrice.plan_id.in_(plan_ids),
                    )
                )
                parent_prices = {int(r.plan_id): int(r.price_cents) for r in parent_prices_res.scalars().all()}

                for pp in payload.plans:
                    pid = int(pp.plan_id)
                    if pid in parent_prices and int(pp.price_cents) < parent_prices[pid]:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Plan {pid} price_cents must be >= parent price ({parent_prices[pid]})",
                        )

            # FULL replace SellerPlanPrice rows
            await db.execute(delete(SellerPlanPrice).where(SellerPlanPrice.seller_id == int(seller.id)))
            for pp in payload.plans:
                db.add(
                    SellerPlanPrice(
                        seller_id=int(seller.id),
                        plan_id=int(pp.plan_id),
                        price_cents=int(pp.price_cents),
                        currency="USD",
                    )
                )

            # ✅ CRITICAL FIX: full replace edge rows too
            await _sync_edge_prices_full_replace(
                db,
                parent_user_id=int(parent_id),
                child_user_id=int(seller.id),
                plan_prices=[(int(pp.plan_id), int(pp.price_cents)) for pp in payload.plans],
                updated_by_user_id=int(admin_user.id),
                currency="USD",
            )

        await db.commit()
        await db.refresh(seller)

        # build response
        parent_alias = User.__table__.alias("parent_user")
        stmt = (
            select(
                User.id,
                User.username,
                User.role,
                User.parent_id,
                parent_alias.c.username.label("parent_username"),
                User.full_name,
                User.email,
                User.phone,
                User.country,
                User.is_active,
                User.created_at,
                WalletAccount.balance_cents,
                WalletAccount.currency,
            )
            .select_from(User)
            .outerjoin(WalletAccount, WalletAccount.user_id == User.id)
            .outerjoin(parent_alias, parent_alias.c.id == User.parent_id)
            .where(User.id == int(seller.id))
        )
        r = (await db.execute(stmt)).one()

        prices: list[SellerPlanPriceOut] = []
        price_rows = await db.execute(
            select(SellerPlanPrice, Plan)
            .join(Plan, Plan.id == SellerPlanPrice.plan_id)
            .where(SellerPlanPrice.seller_id == int(seller.id))
        )
        for spp, pl in price_rows.all():
            prices.append(
                SellerPlanPriceOut(
                    plan_id=int(spp.plan_id),
                    title=pl.title,
                    price_cents=int(spp.price_cents),
                )
            )

        return AdminSellerOut(
            id=int(r.id),
            username=r.username,
            role=r.role,
            parent_id=int(r.parent_id) if r.parent_id is not None else None,
            parent_username=r.parent_username,
            full_name=r.full_name,
            email=r.email,
            phone=r.phone,
            country=r.country,
            is_active=bool(r.is_active),
            created_at=r.created_at,
            balance_cents=int(r.balance_cents) if r.balance_cents is not None else 0,
            currency=r.currency or "USD",
            plans=prices,
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/sellers/{seller_id}/balance")
async def admin_set_seller_balance(
    seller_id: int,
    payload: AdminSetSellerBalanceIn,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    # ensure seller exists
    res = await db.execute(select(User).where(User.id == int(seller_id)))
    seller = res.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    try:
        entries = await admin_set_balance_via_parent(
            db=db,
            admin_user=admin_user,
            target_user_id=int(seller_id),
            target_balance_cents=int(payload.target_balance_cents),
            note=payload.note,
        )

        await db.commit()  # ✅ REQUIRED
        wa = await get_balance(db, int(seller_id))

        return {
            "ok": True,
            "seller_id": int(seller_id),
            "balance_cents": int(wa.balance_cents),
            "currency": wa.currency,
            "tx_count": len(entries),
        }

    except WalletError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        await db.rollback()
        raise


@router.delete("/sellers/{seller_id}")
async def admin_delete_seller(
    seller_id: int,
    payload: AdminDeleteSellerIn,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    res = await db.execute(select(User).where(User.id == int(seller_id)))
    seller = res.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    try:
        entries = await admin_delete_user_return_balance_to_parent(
            db=db,
            admin_user=admin_user,
            target_user_id=int(seller_id),
            note=payload.note,
        )

        await db.commit()  # ✅ REQUIRED
        return {"ok": True, "deleted_seller_id": int(seller_id), "tx_count": len(entries)}

    except WalletError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        await db.rollback()
        raise