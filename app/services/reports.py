from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coupon import Coupon
from app.models.coupon_event import CouponEvent
from app.models.plan import Plan
from app.models.user import User
from app.models.order import Order
from app.models.order_item import OrderItem


class ReportError(Exception):
    pass


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.isoformat().replace("+00:00", "Z")


async def _username_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    user_ids = [int(x) for x in set(user_ids) if x is not None]
    if not user_ids:
        return {}
    res = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
    return {int(r[0]): (r[1] or "") for r in res.all()}


def _ltree_is_descendant_expr(user_path_col, admin_path: str):
    # ltree operator: child_path <@ ancestor_path
    return user_path_col.op("<@")(admin_path)


async def _assert_user_in_admin_subtree(db: AsyncSession, *, current_admin: User, user_id: int) -> None:
    if not getattr(current_admin, "path", None):
        raise ReportError("Current admin has no path; cannot scope subtree.")

    stmt = (
        select(User.id)
        .where(User.id == int(user_id))
        .where(User.role == "seller")
        .where(User.id != current_admin.id)
        .where(_ltree_is_descendant_expr(User.path, current_admin.path))
        .limit(1)
    )
    res = await db.execute(stmt)
    ok = res.scalar_one_or_none()
    if ok is None:
        raise ReportError("Permission denied: seller not under your tree.")


@dataclass
class CouponRow:
    coupon_code: str
    plan_id: int
    plan_title: str
    plan_category: str
    status: str
    created_at: datetime

    created_by_user_id: Optional[int]
    owner_user_id: Optional[int]
    reserved_by_user_id: Optional[int]
    used_by_user_id: Optional[int]

    reserved_at: Optional[datetime]
    used_at: Optional[datetime]

    order_no: Optional[int]
    tx_id: Optional[str]


async def _fetch_coupon_rows(
    db: AsyncSession,
    *,
    current_admin: User,
    generated_by_user_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    used_by_user_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 2000,
) -> list[CouponRow]:
    if not getattr(current_admin, "path", None):
        raise ReportError("Current admin has no path; cannot scope subtree.")

    # If a specific seller is requested, validate it's under admin first
    if generated_by_user_id is not None:
        await _assert_user_in_admin_subtree(db, current_admin=current_admin, user_id=generated_by_user_id)
    if owner_user_id is not None:
        await _assert_user_in_admin_subtree(db, current_admin=current_admin, user_id=owner_user_id)
    if used_by_user_id is not None:
        await _assert_user_in_admin_subtree(db, current_admin=current_admin, user_id=used_by_user_id)

    filters = []

    # Subtree scoping rule:
    # Coupon is included if any of its involved seller fields is under admin subtree.
    # We use joins to users for each relationship and apply ltree condition.
    # Aliases:
    from sqlalchemy.orm import aliased

    UCreated = aliased(User)
    UOwner = aliased(User)
    UReserved = aliased(User)
    UUsed = aliased(User)

    subtree_or = or_(
        and_(Coupon.created_by_user_id.isnot(None), UCreated.id.isnot(None), _ltree_is_descendant_expr(UCreated.path, current_admin.path)),
        and_(Coupon.owner_user_id.isnot(None), UOwner.id.isnot(None), _ltree_is_descendant_expr(UOwner.path, current_admin.path)),
        and_(Coupon.reserved_by_user_id.isnot(None), UReserved.id.isnot(None), _ltree_is_descendant_expr(UReserved.path, current_admin.path)),
        and_(Coupon.used_by_user_id.isnot(None), UUsed.id.isnot(None), _ltree_is_descendant_expr(UUsed.path, current_admin.path)),
    )
    filters.append(subtree_or)

    # Optional filters
    if generated_by_user_id is not None:
        filters.append(Coupon.created_by_user_id == generated_by_user_id)
    if owner_user_id is not None:
        filters.append(Coupon.owner_user_id == owner_user_id)
    if used_by_user_id is not None:
        filters.append(Coupon.used_by_user_id == used_by_user_id)
    if plan_id is not None:
        filters.append(Coupon.plan_id == plan_id)
    if status is not None:
        filters.append(Coupon.status == status)
    if date_from is not None:
        filters.append(Coupon.created_at >= date_from)
    if date_to is not None:
        filters.append(Coupon.created_at <= date_to)

    where_clause = and_(*filters)

    # Join plans + (LEFT) joins to user aliases for subtree scoping
    stmt = (
        select(Coupon, Plan)
        .join(Plan, Plan.id == Coupon.plan_id)
        .outerjoin(UCreated, UCreated.id == Coupon.created_by_user_id)
        .outerjoin(UOwner, UOwner.id == Coupon.owner_user_id)
        .outerjoin(UReserved, UReserved.id == Coupon.reserved_by_user_id)
        .outerjoin(UUsed, UUsed.id == Coupon.used_by_user_id)
        .where(where_clause)
        .order_by(Coupon.created_at.desc(), Coupon.coupon_code.asc())
        .limit(limit)
    )

    res = await db.execute(stmt)
    rows = res.all()

    coupons: list[Coupon] = [r[0] for r in rows]

    # Map coupon_code -> (order_no, tx_id)
    code_list = [c.coupon_code for c in coupons]
    order_map: dict[str, tuple[Optional[int], Optional[str]]] = {}

    if code_list:
        join_stmt = (
            select(OrderItem.coupon_code, Order.order_no, Order.tx_id)
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.coupon_code.in_(code_list))
        )
        join_res = await db.execute(join_stmt)
        for code, order_no, tx_id in join_res.all():
            order_map[str(code)] = (int(order_no) if order_no is not None else None, str(tx_id) if tx_id else None)

    out: list[CouponRow] = []
    for coupon, plan in rows:
        order_no, tx_id = order_map.get(coupon.coupon_code, (None, None))
        out.append(
            CouponRow(
                coupon_code=coupon.coupon_code,
                plan_id=int(coupon.plan_id),
                plan_title=getattr(plan, "title", "") or "",
                plan_category=getattr(plan, "category", "") or "",
                status=coupon.status,
                created_at=coupon.created_at,
                created_by_user_id=coupon.created_by_user_id,
                owner_user_id=coupon.owner_user_id,
                reserved_by_user_id=coupon.reserved_by_user_id,
                used_by_user_id=coupon.used_by_user_id,
                reserved_at=coupon.reserved_at,
                used_at=coupon.used_at,
                order_no=order_no,
                tx_id=tx_id,
            )
        )

    return out


def _build_pdf_bytes(title: str, subtitle_lines: list[str], table_header: list[str], table_rows: list[list[Any]]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
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


async def generate_coupons_history_pdf(
    db: AsyncSession,
    *,
    current_admin: User,
    generated_by_user_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    used_by_user_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 2000,
) -> bytes:
    rows = await _fetch_coupon_rows(
        db,
        current_admin=current_admin,
        generated_by_user_id=generated_by_user_id,
        owner_user_id=owner_user_id,
        used_by_user_id=used_by_user_id,
        plan_id=plan_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )

    user_ids: list[int] = []
    for r in rows:
        for v in [r.created_by_user_id, r.owner_user_id, r.reserved_by_user_id, r.used_by_user_id]:
            if v is not None:
                user_ids.append(int(v))
    uname = await _username_map(db, user_ids)

    subtitle = [
        f"Generated on: {_fmt_dt(datetime.utcnow())}",
        f"Scope: admin_id={current_admin.id} admin_path={getattr(current_admin, 'path', '')}",
        f"Filters: generated_by={generated_by_user_id or ''} owner={owner_user_id or ''} used_by={used_by_user_id or ''} plan_id={plan_id or ''} status={status or ''}",
        f"Date range: from={_fmt_dt(date_from)} to={_fmt_dt(date_to)} | Rows: {len(rows)} (limit={limit})",
    ]

    header = [
        "Coupon",
        "Plan",
        "Status",
        "Created At",
        "Generated By",
        "Owner",
        "Order #",
        "Reserved / Used",
    ]

    body: list[list[Any]] = []
    for r in rows:
        plan_label = f"{r.plan_title} ({r.plan_category})"
        gen = f"{r.created_by_user_id or ''} {uname.get(int(r.created_by_user_id), '') if r.created_by_user_id else ''}".strip()
        owner = f"{r.owner_user_id or ''} {uname.get(int(r.owner_user_id), '') if r.owner_user_id else ''}".strip()
        order_txt = str(r.order_no) if r.order_no is not None else ""
        ru = f"R:{_fmt_dt(r.reserved_at)}\nU:{_fmt_dt(r.used_at)}"
        body.append([r.coupon_code, plan_label, r.status, _fmt_dt(r.created_at), gen, owner, order_txt, ru])

    return _build_pdf_bytes(
        title="Certify — Coupons History Report",
        subtitle_lines=subtitle,
        table_header=header,
        table_rows=body,
    )


async def generate_coupon_trace_pdf(
    db: AsyncSession,
    *,
    coupon_code: str,
    current_admin: User,
) -> bytes:
    if not getattr(current_admin, "path", None):
        raise ReportError("Current admin has no path; cannot scope subtree.")

    # coupon + plan
    stmt = (
        select(Coupon, Plan)
        .join(Plan, Plan.id == Coupon.plan_id)
        .where(Coupon.coupon_code == coupon_code)
        .limit(1)
    )
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise ReportError("Coupon not found.")

    coupon: Coupon = row[0]
    plan: Plan = row[1]

    # Permission scope: coupon must belong to subtree (any involved user under admin path)
    from sqlalchemy.orm import aliased

    UCreated = aliased(User)
    UOwner = aliased(User)
    UReserved = aliased(User)
    UUsed = aliased(User)

    scope_stmt = (
        select(Coupon.coupon_code)
        .select_from(Coupon)
        .outerjoin(UCreated, UCreated.id == Coupon.created_by_user_id)
        .outerjoin(UOwner, UOwner.id == Coupon.owner_user_id)
        .outerjoin(UReserved, UReserved.id == Coupon.reserved_by_user_id)
        .outerjoin(UUsed, UUsed.id == Coupon.used_by_user_id)
        .where(Coupon.coupon_code == coupon_code)
        .where(
            or_(
                and_(Coupon.created_by_user_id.isnot(None), _ltree_is_descendant_expr(UCreated.path, current_admin.path)),
                and_(Coupon.owner_user_id.isnot(None), _ltree_is_descendant_expr(UOwner.path, current_admin.path)),
                and_(Coupon.reserved_by_user_id.isnot(None), _ltree_is_descendant_expr(UReserved.path, current_admin.path)),
                and_(Coupon.used_by_user_id.isnot(None), _ltree_is_descendant_expr(UUsed.path, current_admin.path)),
            )
        )
        .limit(1)
    )
    scope_res = await db.execute(scope_stmt)
    if scope_res.scalar_one_or_none() is None:
        raise ReportError("Permission denied: coupon not under your tree.")

    # order link (if any)
    order_no = None
    tx_id = None
    join_stmt = (
        select(Order.order_no, Order.tx_id)
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.coupon_code == coupon_code)
        .limit(1)
    )
    join_res = await db.execute(join_stmt)
    j = join_res.first()
    if j:
        order_no = int(j[0]) if j[0] is not None else None
        tx_id = str(j[1]) if j[1] else None

    # events timeline
    ev_stmt = (
        select(CouponEvent)
        .where(CouponEvent.coupon_code == coupon_code)
        .order_by(CouponEvent.created_at.asc(), CouponEvent.id.asc())
    )
    ev_res = await db.execute(ev_stmt)
    events = ev_res.scalars().all()

    user_ids: list[int] = []
    for v in [coupon.created_by_user_id, coupon.owner_user_id, coupon.reserved_by_user_id, coupon.used_by_user_id]:
        if v is not None:
            user_ids.append(int(v))
    for ev in events:
        if ev.actor_user_id is not None:
            user_ids.append(int(ev.actor_user_id))

    uname = await _username_map(db, user_ids)

    subtitle = [
        f"Coupon: <b>{coupon.coupon_code}</b>",
        f"Plan: <b>{getattr(plan, 'title', '')}</b> ({getattr(plan, 'category', '')}) | plan_id={coupon.plan_id}",
        f"Status: <b>{coupon.status}</b> | Created: {_fmt_dt(coupon.created_at)}",
        f"Order: #{order_no or ''} | tx_id={tx_id or ''}",
        f"Scope: admin_id={current_admin.id} admin_path={getattr(current_admin, 'path', '')}",
    ]

    header = ["Time", "Event", "Actor", "Meta"]
    body: list[list[Any]] = []

    for ev in events:
        actor = ""
        if ev.actor_user_id is not None:
            actor = f"{int(ev.actor_user_id)} {uname.get(int(ev.actor_user_id), '')}".strip()
        meta_txt = ""
        try:
            meta_txt = str(ev.meta) if ev.meta is not None else ""
        except Exception:
            meta_txt = ""
        body.append([_fmt_dt(ev.created_at), ev.event_type, actor, meta_txt])

    core_block = [
        f"generated_by: {coupon.created_by_user_id or ''} {uname.get(int(coupon.created_by_user_id), '') if coupon.created_by_user_id else ''}".strip(),
        f"owner: {coupon.owner_user_id or ''} {uname.get(int(coupon.owner_user_id), '') if coupon.owner_user_id else ''}".strip(),
        f"reserved_by: {coupon.reserved_by_user_id or ''} {uname.get(int(coupon.reserved_by_user_id), '') if coupon.reserved_by_user_id else ''}".strip(),
        f"used_by: {coupon.used_by_user_id or ''} {uname.get(int(coupon.used_by_user_id), '') if coupon.used_by_user_id else ''}".strip(),
        f"reserved_at: {_fmt_dt(coupon.reserved_at)} | used_at: {_fmt_dt(coupon.used_at)}",
        f"provider_req_id: {coupon.provider_req_id or ''}",
        f"last_failure: {coupon.last_failure_reason or ''} / {coupon.last_failure_step or ''} / {_fmt_dt(coupon.last_failed_at)}",
        f"notes: {coupon.notes or ''}",
    ]

    subtitle.extend([f"<font size=9>{line}</font>" for line in core_block])

    return _build_pdf_bytes(
        title="Certify — Coupon Trace Report",
        subtitle_lines=subtitle,
        table_header=header,
        table_rows=body,
    )
