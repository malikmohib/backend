from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class UserRole(str, Enum):
    admin = "admin"
    seller = "seller"
    agent = "agent"


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: UserRole = Field(default=UserRole.seller)

    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=8)

    # legacy (kept optional to avoid breaking old clients)
    telegram_id: Optional[int] = None

    is_active: bool = True


class AdminCreateUser(UserCreate):
    model_config = ConfigDict(extra="forbid")

    parent_id: Optional[int] = None  # will be ignored: parent is always creator


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    parent_id: Optional[int]

    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None

    telegram_id: Optional[int] = None

    is_active: bool
    created_at: datetime
    path: Optional[str]
    depth: int


class TreeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserOut]
