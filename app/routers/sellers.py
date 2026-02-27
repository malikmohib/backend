from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_seller
from app.models.plan import Plan
from app.models.seller_plan_price import SellerPlanPrice
from app.models.user import User
from app.models.wallet import WalletAccount

# ✅ ADD THIS IMPORT (adjust path to match your project)
from app.models.pricing import SellerEdgePlanPrice

from app.schemas.seller_users_management import (
    SellerChildSellerListResponse,
    SellerChildSellerOut,
    SellerCreateChildSellerRequest,
    SellerDeleteChildIn,
    SellerPlanPriceOut,
    SellerSetChildBalanceIn,
    SellerUpdateChildSellerRequest,
)
from app.services.tree import create_user_under_parent
from app.services.wallet import (
    InsufficientBalance,
    WalletError,
    seller_delete_user_return_balance_to_parent,
    seller_set_balance_via_parent,
)

router = APIRouter(prefix="/sellers", tags=["seller-users"])


async def _get_direct_child_or_404(db: AsyncSession, *, seller_id: int, child_id: int) -> User:
    res = await db.execute(
        select(User).where(
            User.id == int(child_id),
            User.parent_id == int(seller_id),
        )
    )
    child = res.scalar_one_or_none()
    if not child:
        raise HTTPException(status_code=404, detail="User not found")
    return child


async def _seller_allowed_plan_prices(db: AsyncSession, seller_id: int, plan_ids: list[int]) -> dict[int, int]:
    """
    Returns {plan_id: seller_price_cents} for plans the seller currently has in seller_plan_prices.
    """
    if not plan_ids:
        return {}
    res = await db.execute(
        select(SellerPlanPrice).where(
            SellerPlanPrice.seller_id == int(seller_id),
            SellerPlanPrice.plan_id.in_(plan_ids),
        )
    )
    rows = res.scalars().all()
    return {int(r.plan_id): int(r.price_cents) for r in rows}


@router.get("/users", response_model=SellerChildSellerListResponse)
async def seller_list_direct_children(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
) -> SellerChildSellerListResponse:
    # direct children only
    res = await db.execute(
        select(User).where(User.parent_id == int(current_seller.id)).order_by(User.created_at.desc())
    )
    children = res.scalars().all()

    child_ids = [int(u.id) for u in children]

    # wallets
    wallets_by_uid: dict[int, WalletAccount] = {}
    if child_ids:
        wres = await db.execute(select(WalletAccount).where(WalletAccount.user_id.in_(child_ids)))
        wallets = wres.scalars().all()
        wallets_by_uid = {int(w.user_id): w for w in wallets}

    # plans
    plans_by_child: dict[int, list[SellerPlanPriceOut]] = {cid: [] for cid in child_ids}
    if child_ids:
        pp_res = await db.execute(
            select(SellerPlanPrice, Plan)
            .join(Plan, Plan.id == SellerPlanPrice.plan_id)
            .where(SellerPlanPrice.seller_id.in_(child_ids))
        )
        for pp, plan in pp_res.all():
            plans_by_child[int(pp.seller_id)].append(
                SellerPlanPriceOut(
                    plan_id=int(pp.plan_id),
                    title=plan.title,
                    price_cents=int(pp.price_cents),
                )
            )
        for cid in plans_by_child:
            plans_by_child[cid].sort(key=lambda x: x.title)

    items: list[SellerChildSellerOut] = []
    for u in children:
        wa = wallets_by_uid.get(int(u.id))
        items.append(
            SellerChildSellerOut(
                id=int(u.id),
                username=u.username,
                role=u.role,  # always seller in our create endpoint
                parent_id=int(u.parent_id) if u.parent_id is not None else None,
                parent_username=current_seller.username,
                full_name=u.full_name,
                email=u.email,
                phone=u.phone,
                country=u.country,
                is_active=bool(u.is_active),
                created_at=u.created_at,
                balance_cents=int(wa.balance_cents) if wa else 0,
                currency=wa.currency if wa else "USD",
                plans=plans_by_child.get(int(u.id), []),
            )
        )

    return SellerChildSellerListResponse(items=items)


@router.post("/users", response_model=SellerChildSellerOut)
async def seller_create_direct_child(
    payload: SellerCreateChildSellerRequest,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
) -> SellerChildSellerOut:
    """
    Seller creates a direct child seller.
    Role is ALWAYS seller (no role in payload).
    Can assign plans, but only those seller already has.
    Child price must be >= seller price.
    ✅ ALSO creates seller_edge_plan_prices rows for (parent=current_seller -> child).
    """

    try:
        child = await create_user_under_parent(
            db,
            username=payload.username,
            password=payload.password,
            role="seller",
            parent=current_seller,
            telegram_id=None,
            is_active=payload.is_active,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            country=payload.country,
        )
        await db.flush()

        # Ensure wallet exists for the child user
        db.add(WalletAccount(user_id=int(child.id), balance_cents=0, currency="USD"))
        await db.flush()

        # Plans validation
        plan_ids = [int(p.plan_id) for p in payload.plans]
        if len(plan_ids) != len(set(plan_ids)):
            raise HTTPException(status_code=400, detail="Duplicate plan_id in plans payload")

        if plan_ids:
            # validate plans exist and active
            res_plans = await db.execute(select(Plan).where(Plan.id.in_(plan_ids)))
            found = res_plans.scalars().all()
            plans_by_id = {int(p.id): p for p in found}

            missing = [pid for pid in plan_ids if pid not in plans_by_id]
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown plan_id(s): {missing}")

            inactive = [pid for pid, pl in plans_by_id.items() if not bool(pl.is_active)]
            if inactive:
                raise HTTPException(status_code=400, detail=f"Inactive plan_id(s): {inactive}")

            seller_prices = await _seller_allowed_plan_prices(db, int(current_seller.id), plan_ids)

            not_owned = [pid for pid in plan_ids if pid not in seller_prices]
            if not_owned:
                raise HTTPException(status_code=400, detail=f"Forbidden plan_id(s): {not_owned}")

            # enforce child >= seller for each plan
            for pp in payload.plans:
                pid = int(pp.plan_id)
                seller_price = int(seller_prices[pid])
                if int(pp.price_cents) < seller_price:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Plan {pid} price_cents must be >= your price ({seller_price})",
                    )

            # insert child plan prices + edge prices (parent=current_seller -> child)
            for pp in payload.plans:
                pid = int(pp.plan_id)
                price_cents = int(pp.price_cents)

                db.add(
                    SellerPlanPrice(
                        seller_id=int(child.id),
                        plan_id=pid,
                        price_cents=price_cents,
                        currency="USD",
                    )
                )

                db.add(
                    SellerEdgePlanPrice(
                        parent_user_id=int(current_seller.id),
                        child_user_id=int(child.id),
                        plan_id=pid,
                        price_cents=price_cents,
                        currency="USD",
                    )
                )

        await db.commit()
        await db.refresh(child)

        # wallet
        wa_res = await db.execute(select(WalletAccount).where(WalletAccount.user_id == int(child.id)))
        wa = wa_res.scalar_one_or_none()

        # plans for response
        out_plans: list[SellerPlanPriceOut] = []
        if plan_ids:
            pp_res = await db.execute(
                select(SellerPlanPrice, Plan)
                .join(Plan, Plan.id == SellerPlanPrice.plan_id)
                .where(SellerPlanPrice.seller_id == int(child.id))
            )
            for pprow, plan in pp_res.all():
                out_plans.append(
                    SellerPlanPriceOut(
                        plan_id=int(pprow.plan_id),
                        title=plan.title,
                        price_cents=int(pprow.price_cents),
                    )
                )
            out_plans.sort(key=lambda x: x.title)

        return SellerChildSellerOut(
            id=int(child.id),
            username=child.username,
            role=child.role,
            parent_id=int(child.parent_id) if child.parent_id is not None else None,
            parent_username=current_seller.username,
            full_name=child.full_name,
            email=child.email,
            phone=child.phone,
            country=child.country,
            is_active=bool(child.is_active),
            created_at=child.created_at,
            balance_cents=int(wa.balance_cents) if wa else 0,
            currency=wa.currency if wa else "USD",
            plans=out_plans,
        )

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Username already exists (must be unique)")
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


@router.patch("/users/{child_id}", response_model=SellerChildSellerOut)
async def seller_update_direct_child(
    child_id: int,
    payload: SellerUpdateChildSellerRequest,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
) -> SellerChildSellerOut:
    child = await _get_direct_child_or_404(db, seller_id=int(current_seller.id), child_id=int(child_id))

    try:
        if payload.full_name is not None:
            child.full_name = payload.full_name
        if payload.email is not None:
            child.email = payload.email
        if payload.phone is not None:
            child.phone = payload.phone
        if payload.country is not None:
            child.country = payload.country
        if payload.is_active is not None:
            child.is_active = payload.is_active

        # full replace plans if provided
        if payload.plans is not None:
            plan_ids = [int(p.plan_id) for p in payload.plans]
            if len(plan_ids) != len(set(plan_ids)):
                raise HTTPException(status_code=400, detail="Duplicate plan_id in plans payload")

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

            seller_prices = await _seller_allowed_plan_prices(db, int(current_seller.id), plan_ids)
            if plan_ids:
                not_owned = [pid for pid in plan_ids if pid not in seller_prices]
                if not_owned:
                    raise HTTPException(status_code=400, detail=f"Forbidden plan_id(s): {not_owned}")

                for pp in payload.plans:
                    pid = int(pp.plan_id)
                    seller_price = int(seller_prices[pid])
                    if int(pp.price_cents) < seller_price:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Plan {pid} price_cents must be >= your price ({seller_price})",
                        )

            # ✅ FULL REPLACE:
            # 1) delete child seller_plan_prices
            await db.execute(delete(SellerPlanPrice).where(SellerPlanPrice.seller_id == int(child.id)))

            # 2) delete parent->child edge prices (this is the missing part!)
            await db.execute(
                delete(SellerEdgePlanPrice).where(
                    SellerEdgePlanPrice.parent_user_id == int(current_seller.id),
                    SellerEdgePlanPrice.child_user_id == int(child.id),
                )
            )

            # 3) insert new plan prices + edge prices
            for pp in payload.plans:
                pid = int(pp.plan_id)
                price_cents = int(pp.price_cents)

                db.add(
                    SellerPlanPrice(
                        seller_id=int(child.id),
                        plan_id=pid,
                        price_cents=price_cents,
                        currency="USD",
                    )
                )

                db.add(
                    SellerEdgePlanPrice(
                        parent_user_id=int(current_seller.id),
                        child_user_id=int(child.id),
                        plan_id=pid,
                        price_cents=price_cents,
                        currency="USD",
                    )
                )

        await db.commit()
        await db.refresh(child)

        wa_res = await db.execute(select(WalletAccount).where(WalletAccount.user_id == int(child.id)))
        wa = wa_res.scalar_one_or_none()

        out_plans: list[SellerPlanPriceOut] = []
        pp_res = await db.execute(
            select(SellerPlanPrice, Plan)
            .join(Plan, Plan.id == SellerPlanPrice.plan_id)
            .where(SellerPlanPrice.seller_id == int(child.id))
        )
        for pp, plan in pp_res.all():
            out_plans.append(
                SellerPlanPriceOut(
                    plan_id=int(pp.plan_id),
                    title=plan.title,
                    price_cents=int(pp.price_cents),
                )
            )
        out_plans.sort(key=lambda x: x.title)

        return SellerChildSellerOut(
            id=int(child.id),
            username=child.username,
            role=child.role,
            parent_id=int(child.parent_id) if child.parent_id is not None else None,
            parent_username=current_seller.username,
            full_name=child.full_name,
            email=child.email,
            phone=child.phone,
            country=child.country,
            is_active=bool(child.is_active),
            created_at=child.created_at,
            balance_cents=int(wa.balance_cents) if wa else 0,
            currency=wa.currency if wa else "USD",
            plans=out_plans,
        )

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Update failed due to a uniqueness constraint")
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/users/{child_id}/balance")
async def seller_set_child_balance(
    child_id: int,
    payload: SellerSetChildBalanceIn,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
):
    await _get_direct_child_or_404(db, seller_id=int(current_seller.id), child_id=int(child_id))

    try:
        entries = await seller_set_balance_via_parent(
            db=db,
            seller_user=current_seller,
            target_user_id=int(child_id),
            target_balance_cents=int(payload.target_balance_cents),
            note=payload.note,
        )
        await db.commit()
        return {"ok": True, "child_id": int(child_id), "tx_count": len(entries)}
    except InsufficientBalance as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except WalletError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{child_id}")
async def seller_delete_child_seller(
    child_id: int,
    payload: SellerDeleteChildIn,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
):
    await _get_direct_child_or_404(db, seller_id=int(current_seller.id), child_id=int(child_id))

    try:
        entries = await seller_delete_user_return_balance_to_parent(
            db=db,
            seller_user=current_seller,
            target_user_id=int(child_id),
            note=payload.note,
        )
        await db.commit()
        return {"ok": True, "deleted_child_id": int(child_id), "tx_count": len(entries)}
    except WalletError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/subtree", response_model=SellerChildSellerListResponse)
async def seller_view_subtree_direct_only(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(require_seller),
) -> SellerChildSellerListResponse:
    """Legacy endpoint kept for compatibility.

    Seller permission rules forbid exposing grandchildren structure.
    This returns ONLY direct children.
    """
    return await seller_list_direct_children(db=db, current_seller=current_seller)