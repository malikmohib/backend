# app/services/coupons.py
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import Integer, String, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.coupon import Coupon
from app.models.coupon_event import CouponEvent
from app.models.plan import Plan
from app.models.user import User

# ✅ NEW: paid “generate coupons” uses the purchase engine (wallet + ledger + profit share + paid order)
from app.services.purchases import PurchaseError, purchase_plan_and_distribute
from app.services.wallet import InsufficientBalance


def _generate_coupon_code() -> str:
    # DB constraint requires: Certify-[0-9a-f]{8}
    return f"Certify-{secrets.token_hex(4)}"


async def _log_event(
    db: AsyncSession,
    *,
    coupon_code: str,
    actor_user_id: int | None,
    event_type: str,
    meta: dict | None = None,
):
    e = CouponEvent(
        coupon_code=coupon_code,
        actor_user_id=actor_user_id,
        event_type=event_type,
        meta=meta or {},
    )
    db.add(e)


async def admin_generate_coupons(
    db: AsyncSession,
    *,
    plan_id: int,
    count: int,
    created_by_user_id: int,
    owner_user_id: int | None,
    notes: str | None,
) -> list[Coupon]:
    plan = await db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.is_active:
        raise HTTPException(status_code=400, detail="Plan is not active")

    created: list[Coupon] = []

    try:
        for _ in range(count):
            c = Coupon(
                coupon_code=_generate_coupon_code(),
                plan_id=plan_id,
                status="unused",
                created_by_user_id=created_by_user_id,
                owner_user_id=owner_user_id,
                notes=notes,
            )
            db.add(c)
            created.append(c)

            await _log_event(
                db,
                coupon_code=c.coupon_code,
                actor_user_id=created_by_user_id,
                event_type="generated",
                meta={"plan_id": plan_id, "owner_user_id": owner_user_id, "notes": notes},
            )

        await db.commit()

        for c in created[:50]:
            await db.refresh(c)

        return created

    except Exception:
        await db.rollback()
        raise


async def admin_unreserve_coupon(
    db: AsyncSession,
    *,
    coupon_code: str,
    reason: str | None,
    actor_user_id: int | None,
) -> Coupon:
    stmt = select(Coupon).where(Coupon.coupon_code == coupon_code).with_for_update()
    res = await db.execute(stmt)
    coupon = res.scalar_one_or_none()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if coupon.status != "reserved":
        raise HTTPException(status_code=400, detail="Coupon is not reserved")

    try:
        coupon.status = "unused"
        coupon.reserved_by_user_id = None
        coupon.reserved_udid = None
        coupon.reserved_udid_hash = None
        coupon.reserved_udid_suffix = None
        coupon.reserved_at = None

        if reason:
            coupon.last_failure_reason = f"ADMIN_UNRESERVE: {reason}"
            coupon.last_failure_step = "admin_unreserve"
            coupon.last_failed_at = datetime.now(timezone.utc)

        await _log_event(
            db,
            coupon_code=coupon.coupon_code,
            actor_user_id=actor_user_id,
            event_type="unreserved",
            meta={"reason": reason},
        )

        await db.commit()
        await db.refresh(coupon)
        return coupon

    except Exception:
        await db.rollback()
        raise


async def admin_void_coupon(
    db: AsyncSession,
    *,
    coupon_code: str,
    reason: str | None,
    actor_user_id: int | None,
) -> Coupon:
    stmt = select(Coupon).where(Coupon.coupon_code == coupon_code).with_for_update()
    res = await db.execute(stmt)
    coupon = res.scalar_one_or_none()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if coupon.status == "used":
        raise HTTPException(status_code=400, detail="Cannot void a used coupon")

    try:
        coupon.status = "void"

        if reason:
            coupon.last_failure_reason = f"VOID: {reason}"
            coupon.last_failure_step = "admin_void"
            coupon.last_failed_at = datetime.now(timezone.utc)

        await _log_event(
            db,
            coupon_code=coupon.coupon_code,
            actor_user_id=actor_user_id,
            event_type="voided",
            meta={"reason": reason},
        )

        await db.commit()
        await db.refresh(coupon)
        return coupon

    except Exception:
        await db.rollback()
        raise


def _udid_suffix(udid: str) -> str:
    u = (udid or "").strip()
    if len(u) <= 6:
        return u
    return u[-6:]


def _udid_hash_bytes(udid: str) -> bytes:
    # deterministic hash for indexing/matching without exposing whole value
    u = (udid or "").strip().encode("utf-8")
    return hashlib.sha256(u).digest()


async def admin_reserve_coupon(
    db: AsyncSession,
    *,
    coupon_code: str,
    udid: str,
    notes: str | None,
    actor_user_id: int | None,
) -> Coupon:
    stmt = select(Coupon).where(Coupon.coupon_code == coupon_code).with_for_update()
    res = await db.execute(stmt)
    coupon = res.scalar_one_or_none()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if coupon.status != "unused":
        raise HTTPException(status_code=400, detail=f"Coupon is not unused (current: {coupon.status})")

    clean_udid = (udid or "").strip()
    if not clean_udid:
        raise HTTPException(status_code=400, detail="udid is required")

    try:
        coupon.status = "reserved"
        coupon.reserved_by_user_id = actor_user_id
        coupon.reserved_udid = clean_udid
        coupon.reserved_udid_suffix = _udid_suffix(clean_udid)
        coupon.reserved_udid_hash = _udid_hash_bytes(clean_udid)
        coupon.reserved_at = datetime.now(timezone.utc)

        if notes:
            coupon.notes = notes

        await _log_event(
            db,
            coupon_code=coupon.coupon_code,
            actor_user_id=actor_user_id,
            event_type="reserved",
            meta={"udid_suffix": coupon.reserved_udid_suffix},
        )

        await db.commit()
        await db.refresh(coupon)
        return coupon

    except Exception:
        await db.rollback()
        raise


async def admin_mark_coupon_failed(
    db: AsyncSession,
    *,
    coupon_code: str,
    reason: str,
    step: str | None,
    actor_user_id: int | None,
) -> Coupon:
    stmt = select(Coupon).where(Coupon.coupon_code == coupon_code).with_for_update()
    res = await db.execute(stmt)
    coupon = res.scalar_one_or_none()

    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if coupon.status != "reserved":
        raise HTTPException(status_code=400, detail=f"Coupon is not reserved (current: {coupon.status})")

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise HTTPException(status_code=400, detail="reason is required")

    try:
        coupon.last_failure_reason = clean_reason
        coupon.last_failure_step = (step or "unknown").strip()
        coupon.last_failed_at = datetime.now(timezone.utc)

        await _log_event(
            db,
            coupon_code=coupon.coupon_code,
            actor_user_id=actor_user_id,
            event_type="failed",
            meta={"reason": clean_reason, "step": coupon.last_failure_step},
        )

        # IMPORTANT: stays reserved (your rule)
        await db.commit()
        await db.refresh(coupon)
        return coupon

    except Exception:
        await db.rollback()
        raise


async def seller_generate_coupons(
    db: AsyncSession,
    *,
    plan_id: int,
    count: int,
    seller_user_id: int,
    owner_user_id: int | None,
    notes: str | None,
) -> list[Coupon]:
    """
    ✅ PRODUCTION CHANGE (PAID COUPON GENERATION):
    Seller "generate coupons" is a REAL purchase:
      - uses wallet balance (debit seller)
      - posts wallet_ledger rows (purchase_debit + profit/admin credits)
      - applies multi-level hierarchical profit sharing
      - creates a paid order + order_items + coupons atomically

    Owner rule:
      - coupons can be owned by seller OR seller's DIRECT child only (no grandchildren).
    """
    # Load seller
    seller = await db.get(User, int(seller_user_id))
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    if seller.role != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can generate coupons")

    # Determine owner
    target_owner_id = int(owner_user_id) if owner_user_id is not None else int(seller_user_id)

    # Enforce: self or direct child only
    if target_owner_id != int(seller_user_id):
        res = await db.execute(select(User.id, User.parent_id).where(User.id == target_owner_id))
        row = res.first()
        if not row:
            raise HTTPException(status_code=404, detail="Owner user not found")
        parent_id = int(row[1]) if row[1] is not None else None
        if parent_id != int(seller_user_id):
            raise HTTPException(status_code=403, detail="Seller can only generate coupons for self or direct children")

    # Paid purchase flow (this function commits/rolls back internally)
    try:
        result = await purchase_plan_and_distribute(
            db=db,
            buyer=seller,
            plan_id=int(plan_id),
            quantity=int(count),
            note=notes,
            owner_user_id=target_owner_id,
        )
    except InsufficientBalance as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PurchaseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    coupon_codes = result.get("coupon_codes") or []
    if not coupon_codes:
        raise HTTPException(status_code=500, detail="Purchase succeeded but no coupons were generated")

    # Return Coupon ORM rows for those codes (matches router response_model=list[AdminCouponResponse])
    res2 = await db.execute(
        select(Coupon).where(Coupon.coupon_code.in_(coupon_codes)).order_by(Coupon.created_at.desc())
    )
    return list(res2.scalars().all())


async def seller_list_coupons(
    db: AsyncSession,
    *,
    seller_user_id: int,
    status: str | None,
    plan_id: int | None,
    owner_user_id: int | None,
    limit: int,
    offset: int,
) -> list[Coupon]:
    """
    Seller can list coupons where owner is:
      - self
      - direct children

    If owner_user_id is provided, it must be self or direct child.
    """
    # Compute allowed owner ids: self + direct children
    child_res = await db.execute(select(User.id).where(User.parent_id == int(seller_user_id)))
    child_ids = [int(x) for x in child_res.scalars().all()]
    allowed_owner_ids = [int(seller_user_id)] + child_ids

    if owner_user_id is not None:
        oid = int(owner_user_id)
        if oid not in allowed_owner_ids:
            raise HTTPException(status_code=403, detail="Seller can only query self or direct children")
        allowed_owner_ids = [oid]

    stmt = select(Coupon).where(Coupon.owner_user_id.in_(allowed_owner_ids)).order_by(Coupon.created_at.desc())

    if status:
        stmt = stmt.where(Coupon.status == status)
    if plan_id:
        stmt = stmt.where(Coupon.plan_id == int(plan_id))

    res = await db.execute(stmt.limit(int(limit)).offset(int(offset)))
    return res.scalars().all()


def _ltree_is_descendant_expr(user_path_col, ancestor_path: str):
    # ltree operator: child_path <@ ancestor_path
    return user_path_col.op("<@")(ancestor_path)


def _direct_child_bucket_user_id_expr(
    *,
    leaf_id_col,
    leaf_path_col,
    seller_user_id: int,
    seller_path_nlevel: int,
):
    """
    Bucket any leaf user in seller subtree into:
      - seller_user_id (if leaf == seller)
      - else direct child id derived from leaf.path by slicing ONE segment after seller.

    seller_path_nlevel is computed in Python (seller.depth + 1) to avoid calling
    nlevel() on a VARCHAR parameter (which breaks on Postgres).
    """
    # child label ltree like: 'u123'
    child_label_ltree = func.subpath(leaf_path_col, int(seller_path_nlevel), 1)
    child_label_txt = cast(child_label_ltree, String)

    # strip leading "u" => "123"
    child_id_txt = func.substr(child_label_txt, 2)
    child_id_int = cast(child_id_txt, Integer)

    return case(
        (leaf_id_col == int(seller_user_id), int(seller_user_id)),
        else_=child_id_int,
    )


async def seller_recent_coupon_events_rollup(
    db: AsyncSession,
    *,
    seller_user: User,
    limit: int,
    offset: int,
) -> list[dict]:
    """
    Recent coupon events for the seller's *subtree* (direct+indirect),
    but actor identity is bucketed to (self + direct children) based on coupon OWNER.

    Returns dicts matching RecentCouponEventOut fields:
      id, coupon_code, actor_user_id, event_type, created_at, status
    """
    Owner = aliased(User)

    # Bucket by coupon owner path (not by raw actor) to avoid leaking grandchildren.
    seller_path_nlevel = int(getattr(seller_user, "depth", 0)) + 1

    bucket_actor_id = _direct_child_bucket_user_id_expr(
        leaf_id_col=Owner.id,
        leaf_path_col=Owner.path,
        seller_user_id=int(seller_user.id),
        seller_path_nlevel=seller_path_nlevel,
    ).label("bucket_actor_user_id")

    stmt = (
        select(
            CouponEvent.id,
            CouponEvent.coupon_code,
            bucket_actor_id,
            CouponEvent.event_type,
            CouponEvent.created_at,
            Coupon.status,
        )
        .select_from(CouponEvent)
        .join(Coupon, Coupon.coupon_code == CouponEvent.coupon_code)
        .join(Owner, Owner.id == Coupon.owner_user_id)
        .where(_ltree_is_descendant_expr(Owner.path, str(seller_user.path)))
        .order_by(CouponEvent.created_at.desc(), CouponEvent.id.desc())
        .limit(int(limit))
        .offset(int(offset))
    )

    res = await db.execute(stmt)
    items: list[dict] = []
    for r in res.all():
        items.append(
            {
                "id": int(r[0]),
                "coupon_code": str(r[1]),
                "actor_user_id": (int(r[2]) if r[2] is not None else None),
                "event_type": str(r[3]),
                "created_at": r[4],
                "status": str(r[5]),
            }
        )
    return items


async def seller_coupon_events_for_code_bucketed(
    db: AsyncSession,
    *,
    seller_user: User,
    coupon_code: str,
) -> list[CouponEvent]:
    """
    Coupon events for a coupon, only if coupon owner is inside seller subtree.
    Actor IDs are rewritten (in-router) to a bucket to avoid leaking grandchildren identities.

    We return CouponEvent ORM rows; router will map to output schema while bucketizing actor_user_id.
    """
    # Ensure coupon exists and is within seller subtree by OWNER
    Owner = aliased(User)
    stmt = (
        select(Coupon)
        .join(Owner, Owner.id == Coupon.owner_user_id)
        .where(Coupon.coupon_code == coupon_code)
        .where(_ltree_is_descendant_expr(Owner.path, str(seller_user.path)))
    )
    res = await db.execute(stmt)
    coupon = res.scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    ev_stmt = (
        select(CouponEvent)
        .where(CouponEvent.coupon_code == coupon_code)
        .order_by(CouponEvent.created_at.asc(), CouponEvent.id.asc())
    )
    ev_res = await db.execute(ev_stmt)
    return ev_res.scalars().all()