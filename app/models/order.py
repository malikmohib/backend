from __future__ import annotations
from app.models.order_item import OrderItem
from datetime import datetime
from typing import List
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # DB default is nextval('public.order_no_seq')
    order_no: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        server_default=text("nextval('public.order_no_seq')"),
    )

    tx_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)

    buyer_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
    )

    # ✅ MUST match Plan schema
    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("public.plans.id"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_paid_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="paid")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
