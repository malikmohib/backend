from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class PurchaseIn(BaseModel):
    plan_id: int
    note: str | None = None
    quantity: int = Field(default=1, ge=1, le=200)


class PurchaseOut(BaseModel):
    # existing fields (DO NOT REMOVE)
    tx_id: str
    plan_id: int
    buyer_user_id: int
    purchase_price_cents: int
    credits_by_user: dict[int, int]

    # Module E fields
    order_no: int
    quantity: int
    total_paid_cents: int
    coupon_codes: List[str] = Field(default_factory=list)
    keys_text: str = ""
