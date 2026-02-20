from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.core.db import Base


class LtreeType(UserDefinedType):
    """PostgreSQL ltree type (user-defined)."""

    cache_ok = True

    def get_col_spec(self, **kw):
        return "ltree"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(String(32), nullable=False)  # admin/seller/agent

    parent_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )

    # Legacy field (kept for compatibility; we'll stop using it in create flow)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)

    # ✅ New profile fields
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    path: Mapped[Optional[str]] = mapped_column(LtreeType(), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    parent = relationship("User", remote_side=[id], backref="children")
