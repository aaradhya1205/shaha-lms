"""Landing page: callers go to their queue; supervisors get a scoped overview."""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import PTP, Account, CallLog, Office, Payment, PTPStatus, Role, Status, UploadBatch, User
from app.permissions import scope_accounts, team_caller_ids
from app.security import current_user, require_roles
from app.web import render

router = APIRouter()
supervisor = require_roles(Role.HEAD, Role.COO, Role.MANAGER)


@router.get("/")
@router.get("/home")  # stable landing URL (on Netlify, "/" is the static start-up page)
def home(user: User = Depends(current_user)):
    if user.role in (Role.CALLER, Role.CUSTOMER_SERVICE):
        return RedirectResponse("/accounts", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(supervisor), db: Session = Depends(get_db)):
    today = config.today()
    day_start = datetime.combine(today, time.min)
    month_start = today.replace(day=1)
    visible = scope_accounts(select(Account.id), user).subquery()
    in_scope = Account.id.in_(select(visible.c.id))

    totals = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Account.outstanding), 0),
            func.coalesce(func.sum(Account.total_paid), 0),
            func.sum(case((Account.owner_id.is_(None), 1), else_=0)),
        ).where(in_scope)
    ).one()
    by_status = dict(db.execute(
        select(Account.status, func.count()).where(in_scope).group_by(Account.status)).all())

    ptp_counts = dict(db.execute(
        select(PTP.status, func.count()).join(Account, Account.id == PTP.account_id)
        .where(in_scope, PTP.created_at >= day_start - timedelta(days=30)).group_by(PTP.status)).all())
    ptp_due_today = db.scalar(select(func.count()).select_from(Account).where(in_scope, Account.ptp_date == today))
    calls_today = db.scalar(select(func.count()).select_from(CallLog).join(Account, Account.id == CallLog.account_id)
                            .where(in_scope, CallLog.created_at >= day_start))
    collected_month = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                                .join(Account, Account.id == Payment.account_id)
                                .where(in_scope, Payment.payment_date >= month_start))

    # Per-office roll-up (Head / COO only).
    offices = []
    if user.role in Role.GLOBAL:
        offices = db.execute(
            select(Office.name, func.count(Account.id), func.coalesce(func.sum(Account.outstanding), 0),
                   func.coalesce(func.sum(Account.total_paid), 0),
                   func.sum(case((Account.owner_id.is_(None), 1), else_=0)))
            .join(Account, Account.office_id == Office.id).group_by(Office.name).order_by(Office.name)
        ).all()

    # Per-caller performance (team for a manager, everyone for Head / COO).
    caller_filter = User.role == Role.CALLER
    if user.role == Role.MANAGER:
        caller_filter = User.id.in_(team_caller_ids(user))
    callers = list(db.scalars(select(User).where(caller_filter).order_by(User.code)))
    ids = [c.id for c in callers]

    def by_owner(stmt):
        return dict(db.execute(stmt).all())

    open_accounts = by_owner(select(Account.owner_id, func.count()).where(
        Account.owner_id.in_(ids), Account.status.not_in(Status.TERMINAL)).group_by(Account.owner_id))
    calls = by_owner(select(CallLog.user_id, func.count()).where(
        CallLog.user_id.in_(ids), CallLog.created_at >= day_start).group_by(CallLog.user_id))
    due = by_owner(select(Account.owner_id, func.count()).where(
        Account.owner_id.in_(ids), Account.status.not_in(Status.TERMINAL),
        (Account.ptp_date == today) | (Account.next_followup_date <= today)).group_by(Account.owner_id))
    open_ptps = by_owner(select(Account.owner_id, func.count()).where(
        Account.owner_id.in_(ids), Account.ptp_date.is_not(None)).group_by(Account.owner_id))
    broken = by_owner(select(PTP.created_by_id, func.count()).where(
        PTP.created_by_id.in_(ids), PTP.status == PTPStatus.BROKEN,
        PTP.created_at >= day_start - timedelta(days=30)).group_by(PTP.created_by_id))
    collected = by_owner(select(Account.owner_id, func.coalesce(func.sum(Payment.amount), 0))
                         .join(Account, Account.id == Payment.account_id)
                         .where(Account.owner_id.in_(ids), Payment.payment_date >= month_start)
                         .group_by(Account.owner_id))
    team = [{
        "user": c, "open": open_accounts.get(c.id, 0), "calls": calls.get(c.id, 0),
        "due": due.get(c.id, 0), "open_ptps": open_ptps.get(c.id, 0), "broken": broken.get(c.id, 0),
        "collected": collected.get(c.id, 0),
    } for c in callers]
    team.sort(key=lambda r: r["collected"], reverse=True)

    uploads = []
    if user.role in Role.GLOBAL:
        uploads = list(db.scalars(select(UploadBatch).order_by(UploadBatch.id.desc()).limit(5)))

    count, outstanding, paid, unallocated = totals
    return render(
        request, "dashboard.html", user,
        count=count, outstanding=outstanding, paid=paid, unallocated=unallocated or 0,
        recovery=(paid / outstanding * 100) if outstanding else 0,
        by_status=by_status, statuses=Status.ALL, ptp_counts=ptp_counts, ptp_due_today=ptp_due_today,
        calls_today=calls_today, collected_month=collected_month, offices=offices, team=team,
        uploads=uploads, month_label=month_start.strftime("%b %Y"),
    )
