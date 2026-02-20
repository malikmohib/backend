from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.models.wallet import WalletAccount
from app.schemas.users import AdminCreateUser, TreeListResponse, UserOut
from app.services.tree import create_user_under_parent

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/users", response_model=UserOut)
async def admin_create_user(
    payload: AdminCreateUser,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    # ✅ Parent ALWAYS creator
    parent = admin_user

    if payload.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot create admin users via this endpoint")

    try:
        user = await create_user_under_parent(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role.value,
            parent=parent,
            # ✅ stop using telegram_id in the create flow
            telegram_id=None,
            is_active=payload.is_active,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            country=payload.country,
        )

        # ✅ Ensure wallet exists
        existing_wallet = await db.execute(
            select(WalletAccount).where(WalletAccount.user_id == user.id)
        )
        wallet = existing_wallet.scalar_one_or_none()
        if wallet is None:
            db.add(WalletAccount(user_id=user.id, balance_cents=0, currency="USD"))

        await db.commit()
        await db.refresh(user)
        return user
    except Exception:
        await db.rollback()
        raise


@router.get("/users/tree", response_model=TreeListResponse)
async def admin_list_full_tree(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    res = await db.execute(select(User).order_by(User.path.asc().nullsfirst()))
    users = res.scalars().all()
    return {"items": users}
