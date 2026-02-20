from __future__ import annotations

from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.core.security import hash_password


def _ltree_label(user_id: int) -> str:
    return f"u{user_id}"


def build_user_path(parent_path: Optional[str], user_id: int) -> str:
    label = _ltree_label(user_id)
    if not parent_path:
        return label
    return f"{parent_path}.{label}"


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    res = await session.execute(select(User).where(User.id == user_id))
    return res.scalar_one_or_none()


async def _next_user_id(session: AsyncSession) -> int:
    """
    Fetch next value from the users.id sequence.
    Works for BIGSERIAL / Identity-backed sequences.
    """
    res = await session.execute(text("SELECT nextval('public.users_id_seq') AS id"))
    return int(res.scalar_one())


async def create_user_under_parent(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: str,
    parent: Optional[User],
    telegram_id: Optional[int],
    is_active: bool,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    country: Optional[str] = None,
) -> User:
    # 1) prefetch id so path is NOT NULL at insert time
    new_id = await _next_user_id(session)

    parent_path = parent.path if parent else None
    parent_depth = parent.depth if parent else -1

    new_path = build_user_path(parent_path, new_id)
    new_depth = int(parent_depth) + 1

    user = User(
        id=new_id,
        username=username,
        password_hash=hash_password(password),
        role=role,
        parent_id=parent.id if parent else None,
        telegram_id=telegram_id,  # legacy
        full_name=full_name,
        email=email,
        phone=phone,
        country=country,
        is_active=is_active,
        path=new_path,
        depth=new_depth,
    )

    session.add(user)
    return user
