from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, CheckConstraint, func
from sqlalchemy.orm import relationship
from app.core.db import Base


class CouponCategory(Base):
    __tablename__ = "coupon_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    # provider (for now only geek)
    provider = Column(String, nullable=False, default="geek")

    # instant | reservation
    issue_mode = Column(String, nullable=False, default="instant")

    # geek API pool selector (0,1,2)
    pool_type = Column(Integer, nullable=False, default=0)

    # warranty value (allow flexible int >= 0)
    warranty = Column(Integer, nullable=False, default=0)

    # future extensibility
    extra_params = Column(JSON, nullable=False, default=dict)

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("provider IN ('geek')", name="ck_coupon_categories_provider"),
        CheckConstraint(
            "issue_mode IN ('instant','reservation')",
            name="ck_coupon_categories_issue_mode",
        ),
        CheckConstraint("pool_type IN (0,1,2)", name="ck_coupon_categories_pool"),
        CheckConstraint("warranty >= 0", name="ck_coupon_categories_warranty"),
    )