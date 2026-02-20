from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BalanceOut(BaseModel):
    user_id: int
    username: str = ""
    balance_cents: int
    currency: str = "USD"
    updated_at: Optional[datetime] = None


class BalanceHistoryRowOut(BaseModel):
    id: int
    created_at: datetime

    tx_id: str
    entry_kind: str

    amount_cents: int
    balance_after_cents: int
    currency: str = "USD"

    related_user_id: Optional[int] = None
    related_username: str = ""

    plan_id: Optional[int] = None
    plan_title: str = ""

    note: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class BalanceHistoryListOut(BaseModel):
    items: list[BalanceHistoryRowOut]
    limit: int
    offset: int
    total: int


class TxDetailsOut(BaseModel):
    user_id: int
    username: str = ""
    tx_id: str
    rows: list[BalanceHistoryRowOut]
