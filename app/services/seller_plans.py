from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def seller_has_plan_enabled(db: AsyncSession, *, seller_user_id: int, plan_id: int) -> bool:
    q = text(
        """
        SELECT 1
        FROM public.seller_edge_plan_prices sep
        WHERE sep.child_user_id = :seller_user_id
          AND sep.plan_id = :plan_id
        LIMIT 1
        """
    )
    res = await db.execute(q, {"seller_user_id": seller_user_id, "plan_id": plan_id})
    return res.first() is not None


async def list_available_plans_for_seller(db: AsyncSession, *, seller_user_id: int) -> list[dict]:
    q = text(
        """
        SELECT DISTINCT
          p.id,
          p.category,
          p.code,
          p.title
        FROM public.plans p
        JOIN public.seller_edge_plan_prices sep
          ON sep.plan_id = p.id
        WHERE p.is_active = TRUE
          AND sep.child_user_id = :seller_user_id
        ORDER BY p.id ASC
        """
    )
    res = await db.execute(q, {"seller_user_id": seller_user_id})
    rows = res.mappings().all()
    return [dict(r) for r in rows]
