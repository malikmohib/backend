from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.users import UserCreate, TreeListResponse, UserOut
from app.services.tree import create_user_under_parent

router = APIRouter(prefix="/sellers", tags=["sellers"])


def _require_seller_or_admin(user: User) -> None:
    if user.role not in ("seller", "admin"):
        raise HTTPException(status_code=403, detail="Seller only")


@router.post("/users", response_model=UserOut)
async def seller_create_child(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_seller_or_admin(current_user)

    if payload.role == payload.role.admin:
        raise HTTPException(status_code=400, detail="Sellers cannot create admins")

    try:
        user = await create_user_under_parent(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role.value,
            parent=current_user,
            telegram_id=payload.telegram_id,
            is_active=payload.is_active,
        )
        await db.commit()
        await db.refresh(user)
        return user
    except Exception:
        await db.rollback()
        raise


@router.get("/subtree", response_model=TreeListResponse)
async def seller_view_subtree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_seller_or_admin(current_user)

    if not current_user.path:
        # Shouldn’t happen if your admin was initialized with a path.
        raise HTTPException(status_code=500, detail="Current user has no path set")

    # ltree subtree: descendants (including self) => path <@ my_path
    # We use raw SQL text because ltree ops aren’t always nicely wrapped depending on SQLAlchemy version.
    q = text("""
        SELECT *
        FROM users
        WHERE path <@ :my_path
        ORDER BY path ASC
    """)

    res = await db.execute(q, {"my_path": str(current_user.path)})
    rows = res.mappings().all()

    # Convert mappings -> UserOut by re-querying IDs (simple + consistent)
    # If you want faster: map directly, but this is beginner-friendly and safe.
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return {"items": []}

    res2 = await db.execute(select(User).where(User.id.in_(ids)).order_by(User.path.asc()))
    users = res2.scalars().all()
    return {"items": users}
