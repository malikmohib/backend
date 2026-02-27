from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class CouponCategoryBase(BaseModel):
    name: str
    provider: str = "geek"
    issue_mode: str = "instant"
    pool_type: int = Field(0, ge=0, le=2)
    warranty: int = Field(0, ge=0)
    extra_params: Dict[str, Any] = {}
    is_active: bool = True


class CouponCategoryCreate(CouponCategoryBase):
    pass


class CouponCategoryUpdate(BaseModel):
    name: Optional[str] = None
    issue_mode: Optional[str] = None
    pool_type: Optional[int] = Field(None, ge=0, le=2)
    warranty: Optional[int] = Field(None, ge=0)
    extra_params: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class CouponCategoryOut(CouponCategoryBase):
    id: int

    class Config:
        orm_mode = True