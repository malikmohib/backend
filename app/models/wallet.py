from __future__ import annotations

from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import BigInteger, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"
    __table_args__ = {"schema": "public"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),  # ✅ User model is NOT schema-qualified
        primary_key=True,
    )

    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )


class WalletLedger(Base):
    __tablename__ = "wallet_ledger"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tx_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        server_default=func.gen_random_uuid(),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),  # ✅ User model is NOT schema-qualified
        nullable=False,
    )

    entry_kind: Mapped[str] = mapped_column(Text, nullable=False)

    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")

    related_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),  # ✅ User model is NOT schema-qualified
        nullable=True,
    )

    plan_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("public.plans.id", ondelete="SET NULL"),  # ✅ Plan IS schema public
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "metadata" is reserved; use "meta" attribute but DB column "metadata"
    meta: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )


Index("ix_wallet_ledger_user_created", WalletLedger.user_id, WalletLedger.created_at.desc())
Index("ix_wallet_ledger_tx_id", WalletLedger.tx_id)
Index("ix_wallet_ledger_entry_kind", WalletLedger.entry_kind)
