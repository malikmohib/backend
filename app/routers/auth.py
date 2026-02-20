from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.core.security import verify_password, create_access_token, create_refresh_token
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    username = form_data.username
    password = form_data.password

    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")

    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(user_id=user.id, role=user.role)
    refresh_token = create_refresh_token(user_id=user.id, role=user.role)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }
