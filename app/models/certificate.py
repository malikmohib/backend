# app/models/certificate.py
from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.db import Base


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True, index=True)

    coupon_code = Column(
        Text,
        ForeignKey("coupons.coupon_code", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    # ✅ MUST match Plan schema
    plan_id = Column(
        BigInteger,
        ForeignKey("public.plans.id", ondelete="RESTRICT"),
        nullable=False,
    )

    telegram_id = Column(BigInteger, nullable=True)

    udid = Column(Text, nullable=False)
    serial = Column(Text, nullable=False)

    provider_req_id = Column(Text, nullable=True)
    raw_response = Column(JSONB, nullable=False, server_default="{}")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    plan = relationship("Plan", lazy="selectin")
    coupon = relationship("Coupon", lazy="selectin")
