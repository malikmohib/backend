# app/services/coupons.py
from __future__ import annotations
import hashlib

import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.models.coupon_event import CouponEvent
from app.models.plan import Plan


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
