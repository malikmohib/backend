from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.schemas.plans import PlanDropdownOut
from app.services.seller_plans import list_available_plans_for_seller

router = APIRouter(prefix="/sellers/plans", tags=["Seller Plans"])


@router.get("/available", response_model=list[PlanDropdownOut])
async def get_available_plans(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items = await list_available_plans_for_seller(db, seller_user_id=current_user.id)
    return items
