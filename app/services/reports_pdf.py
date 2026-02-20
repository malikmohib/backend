from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plan import Plan
from app.models.user import User


class ReportError(Exception):
    pass


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.isoformat().replace("+00:00", "Z")


async def _get_user_by_username(db: AsyncSession, username: str) -> User:
    res = await db.execute(select(User).where(User.username == username))
    u = res.scalar_one_or_none()
    if u is None:
        raise ReportError("User not found.")
    return u


async def _fetch_coupons_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    scope: str,  # generated | owned | used
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 5000,
) -> list[dict]:
    filters = []

    if scope == "generated":
        filters.append(Coupon.created_by_user_id == user_id)
    elif scope == "owned":
        filters.append(Coupon.owner_user_id == user_id)
    elif scope == "used":
        filters.append(Coupon.used_by_user_id == user_id)
    else:
        raise ReportError("Invalid scope. Use: generated | owned | used")

    if plan_id is not None:
        filters.append(Coupon.plan_id == plan_id)
    if status is not None:
        filters.append(Coupon.status == status)
    if date_from is not None:
        filters.append(Coupon.created_at >= date_from)
    if date_to is not None:
        filters.append(Coupon.created_at <= date_to)

    stmt = (
        select(Coupon, Plan)
        .join(Plan, Plan.id == Coupon.plan_id)
        .where(and_(*filters))
        .order_by(Coupon.created_at.desc(), Coupon.coupon_code.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.all()

    coupons = [r[0] for r in rows]
    code_list = [c.coupon_code for c in coupons]

    # order linkage (optional) coupon_code -> (order_no, tx_id)
    order_map: dict[str, tuple[Optional[int], Optional[str]]] = {}
    if code_list:
        link_stmt = (
            select(OrderItem.coupon_code, Order.order_no, Order.tx_id)
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.coupon_code.in_(code_list))
        )
        link_res = await db.execute(link_stmt)
        for code, order_no, tx_id in link_res.all():
            order_map[str(code)] = (
                int(order_no) if order_no is not None else None,
                str(tx_id) if tx_id else None,
            )

    out: list[dict] = []
    for coupon, plan in rows:
        order_no, tx_id = order_map.get(coupon.coupon_code, (None, None))
        out.append(
            {
                "coupon_code": coupon.coupon_code,
                "status": coupon.status,
                "created_at": coupon.created_at,
                "plan_id": int(coupon.plan_id),
                "plan_title": getattr(plan, "title", "") or "",
                "plan_category": getattr(plan, "category", "") or "",
                "order_no": order_no,
                "tx_id": tx_id,
                "notes": coupon.notes or "",
            }
        )

    return out


def _build_pdf(
    *,
    title: str,
    subtitle_lines: list[str],
    table_header: list[str],
    table_rows: list[list[str]],
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

    data = [table_header] + table_rows
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


async def generate_user_keys_pdf(
    db: AsyncSession,
    *,
    user_id: int,
    username: str,
    scope: str,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 5000,
) -> bytes:
    rows = await _fetch_coupons_for_user(
        db,
        user_id=user_id,
        scope=scope,
        plan_id=plan_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )

    total = len(rows)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    status_summary = ", ".join([f"{k}={v}" for k, v in sorted(by_status.items())]) if by_status else "none"

    subtitle = [
        f"User: <b>{username}</b> (id={user_id})",
        f"Report type: <b>{scope}</b> | Generated at: {_fmt_dt(datetime.utcnow())}",
        f"Filters: plan_id={plan_id or ''} status={status or ''} from={_fmt_dt(date_from)} to={_fmt_dt(date_to)} limit={limit}",
        f"Total keys: <b>{total}</b> | Status breakdown: {status_summary}",
    ]

    header = ["Coupon", "Plan", "Status", "Created", "Order#", "Notes"]
    table_rows: list[list[str]] = []
    for r in rows:
        plan_txt = f"{r['plan_title']} ({r['plan_category']})"
        table_rows.append(
            [
                r["coupon_code"],
                plan_txt,
                r["status"],
                _fmt_dt(r["created_at"]),
                str(r["order_no"] or ""),
                (r["notes"] or "")[:80],
            ]
        )

    title = "Certify — Keys Report"
    return _build_pdf(title=title, subtitle_lines=subtitle, table_header=header, table_rows=table_rows)


async def generate_seller_keys_pdf_by_username(
    db: AsyncSession,
    *,
    username: str,
    scope: str,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 5000,
) -> tuple[bytes, int]:
    u = await _get_user_by_username(db, username)
    pdf_bytes = await generate_user_keys_pdf(
        db,
        user_id=int(u.id),
        username=u.username or username,
        scope=scope,
        plan_id=plan_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return pdf_bytes, int(u.id)
