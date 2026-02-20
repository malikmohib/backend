from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.models.wallet import WalletAccount
from app.schemas.users_tree import AdminUserTreeWithBalanceOut

router = APIRouter(prefix="/admin/users", tags=["Admin - Users Tree"])


@router.get("/tree-with-balance", response_model=AdminUserTreeWithBalanceOut)
async def admin_users_tree_with_balance(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminUserTreeWithBalanceOut:
    """
    Returns all users under current admin (including indirect), with parent links + depth + balance.
    Requires User.path + User.depth exist (you have them in create_user_under_parent()).
    """
    if not getattr(current_admin, "path", None):
        return AdminUserTreeWithBalanceOut(items=[])

    # ltree: child_path <@ ancestor_path
    subtree_expr = User.path.op("<@")(current_admin.path)

    stmt = (
        select(User, WalletAccount)
        .outerjoin(WalletAccount, WalletAccount.user_id == User.id)
        .where(subtree_expr)
        .order_by(User.depth.asc(), User.id.asc())
    )

    res = await db.execute(stmt)
    rows = res.all()

    items = []
    for u, wa in rows:
        if u.id == current_admin.id:
            continue  # hide self from list

        items.append(
            {
                "id": int(u.id),
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "parent_id": int(u.parent_id) if u.parent_id is not None else None,
                "depth": int(getattr(u, "depth", 0) or 0),
                "is_active": bool(u.is_active),
                "balance_cents": int(wa.balance_cents) if wa is not None else 0,
                "currency": wa.currency if wa is not None else "USD",
            }
        )

    return AdminUserTreeWithBalanceOut(items=items)
