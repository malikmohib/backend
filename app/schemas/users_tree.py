from __future__ import annotations

from pydantic import BaseModel


class AdminUserTreeWithBalanceItem(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    role: str
    parent_id: int | None = None
    depth: int
    is_active: bool
    balance_cents: int
    currency: str = "USD"


class AdminUserTreeWithBalanceOut(BaseModel):
    items: list[AdminUserTreeWithBalanceItem]
