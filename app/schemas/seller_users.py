from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SellerChildRole(str, Enum):
    seller = "seller"
    agent = "agent"


class SellerPlanAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int
    price_cents: int = Field(gt=0)


class SellerCreateChildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)

    # Role is ALWAYS seller
    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    is_active: bool = True

    plans: list[SellerPlanAssignment] = Field(default_factory=list)

    initial_balance_cents: int = Field(default=0, ge=0)


class SellerUpdateChildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[SellerChildRole] = None

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    is_active: Optional[bool] = None


class SellerChildOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    username: str
    role: str
    parent_id: int

    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None

    is_active: bool
    created_at: datetime

    balance_cents: int
    currency: str


class SellerChildrenListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SellerChildOut]