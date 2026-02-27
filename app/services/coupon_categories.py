from app.models.coupon_category import CouponCategory
from datetime import datetime


def build_coupon_category_snapshot(cat: CouponCategory) -> dict:
    """
    Freeze category config into coupon at creation time.
    """
    return {
        "version": 1,
        "frozen_at": datetime.utcnow().isoformat(),
        "provider": cat.provider,
        "issue_mode": cat.issue_mode,
        "pool_type": cat.pool_type,
        "warranty": cat.warranty,
        "extra_params": cat.extra_params or {},
    }