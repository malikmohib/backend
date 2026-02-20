from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.db import Base


class CouponEvent(Base):
    __allow_unmapped__ = True

    __tablename__ = "coupon_events"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    coupon_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("coupons.coupon_code", ondelete="CASCADE"),
        nullable=False,
    )

    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)

    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
