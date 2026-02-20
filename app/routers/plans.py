from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.plans import PlanDropdownOut
from app.services.plans import public_list_active_plans

router = APIRouter(prefix="/plans", tags=["Plans"])


@router.get("", response_model=list[PlanDropdownOut])
async def list_active_plans(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(default=None),
):
    return await public_list_active_plans(db, category=category)
