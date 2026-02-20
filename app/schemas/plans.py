# app/schemas/plans.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class PlanCreate(BaseModel):
    category: str
    code: str
    title: str
    warranty_days: int = Field(..., ge=0)
    is_instant: bool = True
    is_active: bool = True

    # ✅ dynamic provider params for external API payload
    provider_api_params: dict = Field(default_factory=dict)


class PlanUpdate(BaseModel):
    category: str | None = None
    code: str | None = None
    title: str | None = None
    warranty_days: int | None = Field(default=None, ge=0)
    is_instant: bool | None = None
    is_active: bool | None = None
    provider_api_params: dict | None = None


class PlanOut(BaseModel):
    id: int
    category: str
    code: str
    title: str
    warranty_days: int
    is_instant: bool
    is_active: bool
    provider_api_params: dict
    created_at: datetime

    class Config:
        from_attributes = True

class PlanDropdownOut(BaseModel):
    id: int
    title: str
    category: str
    is_active: bool

    class Config:
        from_attributes = True