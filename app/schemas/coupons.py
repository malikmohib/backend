# app/schemas/coupons.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class AdminCouponGenerateRequest(BaseModel):
    plan_id: int
    count: int = Field(1, ge=1, le=500)
    notes: str | None = None


class AdminCouponResponse(BaseModel):
    coupon_code: str
    plan_id: int
    status: str

    created_by_user_id: int | None
    owner_user_id: int | None

    reserved_by_user_id: int | None
    reserved_udid_suffix: str | None
    reserved_at: datetime | None

    used_by_user_id: int | None
    used_udid_suffix: str | None
    used_at: datetime | None

    last_failure_reason: str | None
    last_failure_step: str | None
    last_failed_at: datetime | None

    provider_req_id: str | None
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AdminCouponUnreserveRequest(BaseModel):
    reason: str | None = None


class AdminCouponVoidRequest(BaseModel):
    reason: str | None = None

class AdminCouponPlanOut(BaseModel):
    plan_id: int
    plan_code: str
    plan_title: str
    provider_api_params: dict

    class Config:
        from_attributes = True
class AdminCouponReserveRequest(BaseModel):
    udid: str
    notes: str | None = None


class AdminCouponFailRequest(BaseModel):
    reason: str
    step: str | None = None
