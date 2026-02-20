from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.user import User


class OrdersPdfError(Exception):
    pass


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    # show readable local-ish format; keep ISO to avoid timezone confusion
    return dt.isoformat().replace("+00:00", "Z")


def _money(cents: int) -> str:
    # USD only
    dollars = cents / 100.0
    return f"${dollars:,.2f}"


async def _get_user_by_username(db: AsyncSession, username: str) -> User:
    res = await db.execute(select(User).where(User.username == username))
    u = res.scalar_one_or_none()
    if u is None:
        raise OrdersPdfError("User not found.")
    return u


def _build_pdf(
    *,
    title: str,
    subtitle_lines: list[str],
    header: list[str],
    rows: list[list[str]],
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{title}</b>", styles["Title"]))
    story.append(Spacer(1, 6))

    for line in subtitle_lines:
        story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 10))

    data = [header] + rows
    tbl = Table(data, repeatRows=1)

    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    story.append(tbl)
    doc.build(story)
    return buf.getvalue()


async def generate_orders_items_pdf(
    db: AsyncSession,
    *,
    buyer_user_id: int,
    username: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    plan_id: Optional[int] = None,
    limit: int = 5000,
) -> bytes:
    filters = [Order.buyer_user_id == buyer_user_id]

    if date_from is not None:
        filters.append(Order.created_at >= date_from)
    if date_to is not None:
        filters.append(Order.created_at <= date_to)
    if plan_id is not None:
        filters.append(Order.plan_id == plan_id)

    stmt = (
        select(Order, OrderItem, Plan)
        .select_from(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Plan, Plan.id == Order.plan_id)
        .where(and_(*filters))
        .order_by(Order.created_at.desc(), Order.order_no.desc(), OrderItem.id.asc())
        .limit(limit)
    )

    res = await db.execute(stmt)
    rows = res.all()

    subtitle = [
        f"Seller/User: <b>{username}</b> (id={buyer_user_id})",
        f"Generated at: {_fmt_dt(datetime.utcnow())}",
        f"Filters: plan_id={plan_id or ''} from={_fmt_dt(date_from)} to={_fmt_dt(date_to)} | Rows: {len(rows)} (limit={limit})",
    ]

    header = ["Order#", "Date/Time", "Plan", "Qty", "Unit Price", "Total Paid", "Coupon", "Serial"]
    body: list[list[str]] = []

    for o, oi, p in rows:
        plan_txt = f"{getattr(p, 'title', '')} ({getattr(p, 'category', '')})"
        body.append(
            [
                str(int(o.order_no)),
                _fmt_dt(o.created_at),
                plan_txt,
                str(int(o.quantity)),
                _money(int(o.unit_price_cents)),
                _money(int(o.total_paid_cents)),
                oi.coupon_code,
                oi.serial or "",
            ]
        )

    return _build_pdf(
        title="Certify — Orders Items Report",
        subtitle_lines=subtitle,
        header=header,
        rows=body,
    )


async def generate_orders_items_pdf_by_username(
    db: AsyncSession,
    *,
    username: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    plan_id: Optional[int] = None,
    limit: int = 5000,
) -> tuple[bytes, int]:
    u = await _get_user_by_username(db, username)
    pdf_bytes = await generate_orders_items_pdf(
        db,
        buyer_user_id=int(u.id),
        username=u.username or username,
        date_from=date_from,
        date_to=date_to,
        plan_id=plan_id,
        limit=limit,
    )
    return pdf_bytes, int(u.id)
