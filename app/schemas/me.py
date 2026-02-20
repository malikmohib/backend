from __future__ import annotations

from pydantic import BaseModel, Field


class MeOut(BaseModel):
    id: int
    username: str
    role: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    is_active: bool

    balance_cents: int
    currency: str = "USD"


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)
    confirm_new_password: str = Field(..., min_length=6)
