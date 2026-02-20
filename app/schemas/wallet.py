from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic import BaseModel, Field

try:
    # Pydantic v2
    from pydantic import ConfigDict
except Exception:  # pragma: no cover
    ConfigDict = None


class WalletBalanceOut(BaseModel):
    user_id: int
    balance_cents: int
    currency: str = "USD"


class TxOut(BaseModel):
    tx_id: str
    created_at: datetime
    message: str


# -------------------------
# Admin payloads
# -------------------------

class AdminTopupIn(BaseModel):
    # admin_wallet.py expects payload.user_id
    # allow both keys in request JSON: user_id OR target_user_id
    user_id: int = Field(..., alias="target_user_id")
    amount_cents: int = Field(..., ge=1)
    note: Optional[str] = None

    # Allow reading by field name even if alias is used
    if ConfigDict is not None:
        model_config = ConfigDict(populate_by_name=True)


# -------------------------
# Seller payloads
# -------------------------

class TransferIn(BaseModel):
    child_user_id: int
    amount_cents: int = Field(..., ge=1)
    note: Optional[str] = None


class AdjustChildBalanceIn(BaseModel):
    child_user_id: int
    target_balance_cents: int = Field(..., ge=0)
    note: Optional[str] = None

class AdminAdjustBalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int  # allow negative
    note: Optional[str] = Field(default=None, max_length=500)

class AdminAdjustBalanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int
    note: Optional[str] = Field(default=None, max_length=500)

class WalletLedgerRowOut(BaseModel):
    id: int
    tx_id: str
    user_id: Optional[int]
    username: Optional[str]
    entry_kind: str
    amount_cents: int
    currency: str
    related_user_id: Optional[int]
    related_username: Optional[str]
    note: Optional[str]
    created_at: datetime


class WalletLedgerListOut(BaseModel):
    items: List[WalletLedgerRowOut]
    offset: int
    limit: int