from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("public.orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    coupon_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("coupons.coupon_code"),
        nullable=False,
        unique=True,
    )

    serial: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    order = relationship("Order", back_populates="items")
