# app/models/coupon.py
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import relationship

from app.core.db import Base


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("coupon_code ~ '^Certify-[0-9a-f]{8}$'", name="coupon_code_format_chk"),
        CheckConstraint(
            "status IN ('unused','reserved','used','void')",
            name="coupons_status_check",
        ),
    )

    coupon_code = Column(Text, primary_key=True)

    # ✅ MUST match Plan schema
    plan_id = Column(BigInteger, ForeignKey("public.plans.id"), nullable=False)

    status = Column(Text, nullable=False)

    created_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    owner_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)

    reserved_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    reserved_udid = Column(Text, nullable=True)
    reserved_at = Column(DateTime(timezone=True), nullable=True)

    used_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    used_udid = Column(Text, nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    last_failure_reason = Column(Text, nullable=True)
    last_failure_step = Column(Text, nullable=True)
    last_failed_at = Column(DateTime(timezone=True), nullable=True)

    provider_req_id = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    reserved_udid_hash = Column(BYTEA, nullable=True)
    reserved_udid_suffix = Column(Text, nullable=True)
    used_udid_hash = Column(BYTEA, nullable=True)
    used_udid_suffix = Column(Text, nullable=True)

    plan = relationship("Plan", back_populates="coupons", lazy="selectin")
