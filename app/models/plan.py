# app/models/plan.py
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.db import Base


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("category IN ('iphone','ipad')", name="plans_category_check"),
        CheckConstraint("warranty_days >= 0", name="plans_warranty_days_check"),
        {"schema": "public"},  # ✅ CRITICAL: must match FK schema
    )

    id = Column(Integer, primary_key=True, index=True)

    category = Column(Text, nullable=False)
    code = Column(Text, nullable=False, unique=True)
    title = Column(Text, nullable=False)

    warranty_days = Column(Integer, nullable=False)
    is_instant = Column(Boolean, nullable=False, server_default="true")
    is_active = Column(Boolean, nullable=False, server_default="true")

    # Dynamic provider API parameters
    provider_api_params = Column(JSONB, nullable=False, server_default="{}")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # optional relationship
    coupons = relationship("Coupon", back_populates="plan", lazy="selectin")
