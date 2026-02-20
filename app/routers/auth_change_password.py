from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import verify_password, hash_password
from app.models.user import User
from app.schemas.me import ChangePasswordIn

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1) confirm match
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(status_code=400, detail="New password and confirmation do not match.")

    # 2) verify current
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    # 3) prevent same password
    if verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from current password.")

    # 4) update
    current_user.password_hash = hash_password(payload.new_password)
    db.add(current_user)
    await db.commit()

    return {"message": "Password changed successfully."}
