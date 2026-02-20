from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class CouponEventOut(BaseModel):
    id: int
    coupon_code: str
    actor_user_id: int | None
    event_type: str
    meta: dict
    created_at: datetime

    class Config:
        from_attributes = True


class RecentCouponEventOut(BaseModel):
    id: int
    coupon_code: str
    actor_user_id: int | None
    event_type: str
    created_at: datetime
    status: str  # derived from Coupon.status

    class Config:
        from_attributes = True
