from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CouponTraceEventOut(BaseModel):
    id: int
    created_at: datetime
    event_type: str
    actor_user_id: Optional[int] = None
    actor_username: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class CouponTraceOut(BaseModel):
    coupon_code: str
    status: str

    plan_id: int
    plan_title: str = ""
    plan_category: str = ""

    created_at: datetime
    created_by_user_id: Optional[int] = None
    created_by_username: str = ""

    owner_user_id: Optional[int] = None
    owner_username: str = ""

    reserved_by_user_id: Optional[int] = None
    reserved_by_username: str = ""
    reserved_udid: Optional[str] = None
    reserved_at: Optional[datetime] = None

    used_by_user_id: Optional[int] = None
    used_by_username: str = ""
    used_udid: Optional[str] = None
    used_at: Optional[datetime] = None

    provider_req_id: Optional[str] = None
    notes: Optional[str] = None

    last_failure_reason: Optional[str] = None
    last_failure_step: Optional[str] = None
    last_failed_at: Optional[datetime] = None

    # order linkage (if this coupon came from a purchase order)
    order_no: Optional[int] = None
    tx_id: Optional[str] = None

    # optional timeline for dashboard
    events: list[CouponTraceEventOut] = Field(default_factory=list)
