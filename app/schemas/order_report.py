from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OrderReportRowOut(BaseModel):
    order_no: int
    created_at: datetime

    plan_id: int
    plan_title: str
    plan_category: str

    quantity: int
    unit_price_cents: int
    total_paid_cents: int
    currency: str = "USD"

    # stacked fields
    coupon_codes: list[str]
    serials: list[str]

    # UI helpers
    keys_text: str
    serials_text: str


class OrderReportOut(BaseModel):
    username: str
    buyer_user_id: Optional[int] = None  # ✅ allow "ALL sellers" mode

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    plan_id: Optional[int] = None
    status: Optional[str] = None

    items: list[OrderReportRowOut]
    total: int
