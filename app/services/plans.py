from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.plan import Plan


async def admin_create_plan(db: AsyncSession, *, data) -> Plan:
    plan = Plan(
        category=data.category,
        code=data.code,
        title=data.title,
        warranty_days=data.warranty_days,
        is_instant=data.is_instant,
        is_active=data.is_active,
    )

    db.add(plan)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Plan code already exists (must be unique)")
    await db.refresh(plan)
    return plan


async def admin_get_plan(db: AsyncSession, *, plan_id: int) -> Plan:
    res = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = res.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


async def admin_list_plans(
    db: AsyncSession,
    *,
    category: str | None,
    is_active: bool | None,
) -> list[Plan]:
    stmt = select(Plan)

    if category:
        stmt = stmt.where(Plan.category == category)

    if is_active is not None:
        stmt = stmt.where(Plan.is_active == is_active)

    stmt = stmt.order_by(Plan.id.asc())

    res = await db.execute(stmt)
    return list(res.scalars().all())


async def admin_update_plan(db: AsyncSession, *, plan_id: int, data) -> Plan:
    plan = await admin_get_plan(db, plan_id=plan_id)

    plan.category = data.category
    plan.code = data.code
    plan.title = data.title
    plan.warranty_days = data.warranty_days
    plan.is_instant = data.is_instant
    plan.is_active = data.is_active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Plan code already exists (must be unique)")

    await db.refresh(plan)
    return plan


async def admin_set_plan_active(db: AsyncSession, *, plan_id: int, is_active: bool) -> Plan:
    plan = await admin_get_plan(db, plan_id=plan_id)
    plan.is_active = is_active
    await db.commit()
    await db.refresh(plan)
    return plan


async def public_list_active_plans(db: AsyncSession, *, category: str | None) -> list[Plan]:
    stmt = select(Plan).where(Plan.is_active.is_(True))

    if category:
        stmt = stmt.where(Plan.category == category)

    stmt = stmt.order_by(Plan.id.asc())

    res = await db.execute(stmt)
    return list(res.scalars().all())
