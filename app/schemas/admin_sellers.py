from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.users import UserRole


class SellerPlanPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int
    price_cents: int = Field(ge=0)


class AdminCreateSellerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: UserRole = Field(default=UserRole.seller)

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    is_active: bool = True

    plans: list[SellerPlanPriceIn] = Field(default_factory=list)


class SellerPlanPriceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int
    title: str
    price_cents: int


class AdminSellerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    username: str
    role: str
    parent_id: int | None
    parent_username: str | None

    full_name: str | None
    email: str | None
    phone: str | None
    country: str | None

    is_active: bool
    created_at: datetime

    balance_cents: int
    currency: str

    plans: list[SellerPlanPriceOut]


class AdminSellerListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminSellerOut]

class AdminUpdateSellerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[UserRole] = None

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    is_active: Optional[bool] = None

    # If provided => replace seller plan prices fully
    plans: Optional[list[SellerPlanPriceIn]] = None
class AdminUpdateSellerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[UserRole] = None

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    is_active: Optional[bool] = None

    # If provided => replace seller plan prices fully
    plans: Optional[list[SellerPlanPriceIn]] = None
class AdminSetSellerBalanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_balance_cents: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)

class AdminDeleteSellerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default="Return balance to parent (delete user)", max_length=500)

class AdminDeleteSellerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default="Return balance to parent (delete user)",
        max_length=500,
    )