from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    PrimaryKeyConstraint,
    String,
    func,
)
from app.core.db import Base


class AdminPlanBasePrice(Base):
    __tablename__ = "admin_plan_base_prices"
    __table_args__ = {"schema": "public"}

    # NOTE: We intentionally do NOT declare SQLAlchemy ForeignKey() here.
    # The DB schema already has the FK constraints. This avoids metadata resolution errors.
    plan_id = Column(BigInteger, primary_key=True)

    base_price_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)

    updated_by_user_id = Column(BigInteger, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SellerEdgePlanPrice(Base):
    __tablename__ = "seller_edge_plan_prices"
    __table_args__ = (
        PrimaryKeyConstraint("parent_user_id", "child_user_id", "plan_id", name="seller_edge_plan_prices_pkey"),
        {"schema": "public"},
    )

    # NOTE: No SQLAlchemy ForeignKey() for same reason as above.
    parent_user_id = Column(BigInteger, nullable=False)
    child_user_id = Column(BigInteger, nullable=False)
    plan_id = Column(BigInteger, nullable=False)

    price_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)

    is_admin_override = Column(Boolean, nullable=False, server_default="false")

    updated_by_user_id = Column(BigInteger, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
