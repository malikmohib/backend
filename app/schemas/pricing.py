from datetime import datetime
from pydantic import BaseModel, Field


# -------- Admin base prices --------

class AdminBasePriceUpsertIn(BaseModel):
    plan_id: int
    base_price_cents: int = Field(ge=0)
    currency: str = Field(min_length=1, max_length=10)


class AdminBasePriceOut(BaseModel):
    plan_id: int
    base_price_cents: int
    currency: str
    updated_by_user_id: int
    updated_at: datetime


# -------- Edge prices (seller/admin) --------

class SellerEdgePriceUpsertIn(BaseModel):
    child_user_id: int
    plan_id: int
    price_cents: int = Field(ge=0)
    currency: str = Field(min_length=1, max_length=10)


class AdminEdgePriceUpsertIn(BaseModel):
    parent_user_id: int
    child_user_id: int
    plan_id: int
    price_cents: int = Field(ge=0)
    currency: str = Field(min_length=1, max_length=10)


class EdgePriceOut(BaseModel):
    parent_user_id: int
    child_user_id: int
    plan_id: int
    price_cents: int
    currency: str
    is_admin_override: bool
    updated_by_user_id: int
    updated_at: datetime


class ParentCostOut(BaseModel):
    parent_user_id: int
    plan_id: int
    parent_cost_cents: int
    currency: str
    source: str  # "admin_base_price" or "edge_price"
