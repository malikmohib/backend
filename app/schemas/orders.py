from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class OrderOut(BaseModel):
    order_no: int
    tx_id: str

    buyer_user_id: int
    purchaser_username: str = ""

    plan_id: int
    plan_title: str = ""
    plan_category: str = ""

    quantity: int
    unit_price_cents: int
    total_paid_cents: int
    currency: str
    status: str

    created_at: datetime

    coupon_codes: List[str] = Field(default_factory=list)
    keys_text: str = ""

    # UI convenience: blank initially until bot fills serials
    serial: Optional[str] = ""


class OrdersListOut(BaseModel):
    items: List[OrderOut] = Field(default_factory=list)
    limit: int
    offset: int
    total: int
