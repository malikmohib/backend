# app/models/coupon_event.py
from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.db import Base


class CouponEvent(Base):
    __tablename__ = "coupon_events"

    id = Column(BigInteger, primary_key=True, index=True)
    coupon_code = Column(Text, ForeignKey("coupons.coupon_code", ondelete="CASCADE"), nullable=False)

    actor_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)

    event_type = Column(Text, nullable=False)  # e.g. generated, voided, unreserved
    meta = Column(JSONB, nullable=False, server_default="{}")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    coupon = relationship("Coupon", lazy="selectin")
