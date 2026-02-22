from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SellerPlanPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: int
    price_cents: int = Field(ge=0)


class SellerPlanPriceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: int
    title: str
    price_cents: int


class SellerCreateChildSellerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)

    # ✅ REQUIRED (not optional anymore)
    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=5, max_length=255)
    phone: str = Field(min_length=3, max_length=32)
    country: str = Field(min_length=2, max_length=8)

    is_active: bool = True
    plans: list[SellerPlanPriceIn] = Field(default_factory=list)

class SellerUpdateChildSellerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    is_active: Optional[bool] = None

    # If provided => replace seller plan prices fully
    plans: Optional[list[SellerPlanPriceIn]] = None


class SellerSetChildBalanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_balance_cents: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)


class SellerDeleteChildIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default="Return balance to parent (delete user)", max_length=500)


class SellerChildSellerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    username: str
    role: str  # always "seller"
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


class SellerChildSellerListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SellerChildSellerOut]