from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# IMPORTANT:
# This imports ALL models so SQLAlchemy registers tables + FKs correctly
import app.models  # noqa: F401

# Routers
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.sellers import router as sellers_router

from app.routers.admin_pricing import router as admin_pricing_router
from app.routers.seller_pricing import router as seller_pricing_router

from app.routers.admin_plans import router as admin_plans_router
from app.routers.plans import router as plans_router
from app.routers.sellers_plans import router as sellers_plans_router

from app.routers.admin_wallet import router as admin_wallet_router
from app.routers.seller_wallet import router as seller_wallet_router

from app.routers.purchases import router as purchases_router

from app.routers.admin_coupons import router as admin_coupons_router
from app.routers.admin_coupon_events import router as admin_coupon_events_router
from app.routers.seller_coupons import router as seller_coupons_router
from app.routers.seller_coupon_events import router as seller_coupon_events_router

# Module E
from app.routers.admin_orders import router as admin_orders_router
from app.routers.seller_orders import router as seller_orders_router

from app.routers.admin_reports import router as admin_reports_router
from app.routers.admin_coupon_trace import router as admin_coupon_trace_router

from app.routers.seller_reports import router as seller_reports_router
from app.routers.admin_reports_pdf import router as admin_reports_pdf_router

from app.routers.seller_orders_pdf import router as seller_orders_pdf_router
from app.routers.admin_orders_pdf import router as admin_orders_pdf_router

from app.routers.seller_balance_history import router as seller_balance_history_router
from app.routers.admin_balance_history import router as admin_balance_history_router

from app.routers.seller_order_report import router as seller_order_report_router
from app.routers.admin_order_report import router as admin_order_report_router

from app.routers.seller_coupon_trace import router as seller_coupon_trace_router
from app.routers.admin_dashboard import router as admin_dashboard_router
from app.routers.seller_dashboard import router as seller_dashboard_router

from app.routers import admin_sellers
from app.routers.admin_users_tree import router as admin_users_tree_router

from app.routers.me import router as me_router
from app.routers.auth_change_password import router as auth_change_password_router

# ✅ NEW: seller users management (admin-like)
from app.routers.seller_users_management import router as seller_users_management_router
from app.routers.seller_balance_history import router as seller_balance_history_router
from app.routers.seller_balance_history_rollup import router as seller_balance_history_rollup_router
from app.routers.admin_balance_history import router as admin_balance_history_router
from app.routers import admin_coupon_categories, bot_coupons

app = FastAPI()

# ✅ CORS for Next.js dev server (frontend)
# Add your Vercel domain later when you deploy frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth & users
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(sellers_router)

# Pricing
app.include_router(admin_pricing_router)
app.include_router(seller_pricing_router)

# Plans
app.include_router(admin_plans_router)
app.include_router(plans_router)
app.include_router(sellers_plans_router)

# Wallet
app.include_router(admin_wallet_router)
app.include_router(seller_wallet_router)

# Purchases
app.include_router(purchases_router)

# Coupons
app.include_router(admin_coupons_router)
app.include_router(admin_coupon_events_router)
app.include_router(seller_coupons_router)
app.include_router(seller_coupon_events_router)

# Orders (Module E)
app.include_router(admin_orders_router)
app.include_router(seller_orders_router)

app.include_router(admin_reports_router)
app.include_router(admin_coupon_trace_router)

app.include_router(seller_reports_router)
app.include_router(admin_reports_pdf_router)

app.include_router(seller_orders_pdf_router)
app.include_router(admin_orders_pdf_router)

app.include_router(seller_balance_history_router)
app.include_router(admin_balance_history_router)

app.include_router(seller_order_report_router)
app.include_router(admin_order_report_router)

app.include_router(seller_coupon_trace_router)
app.include_router(admin_dashboard_router)
app.include_router(seller_dashboard_router)

app.include_router(admin_sellers.router)
app.include_router(admin_users_tree_router)

# ✅ NEW
app.include_router(seller_users_management_router)

app.include_router(me_router)
app.include_router(auth_change_password_router)
app.include_router(seller_balance_history_router)
app.include_router(seller_balance_history_rollup_router)
app.include_router(admin_balance_history_router)

app.include_router(admin_coupon_categories.router)
app.include_router(bot_coupons.router)