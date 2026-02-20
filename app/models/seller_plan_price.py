from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class SellerPlanPrice(Base):
    __tablename__ = "seller_plan_prices"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # DB column is seller_id (FK -> users.id)
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # DB column is bigint (FK -> public.plans.id)
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("public.plans.id", ondelete="CASCADE"), nullable=False, index=True
    )

    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )
