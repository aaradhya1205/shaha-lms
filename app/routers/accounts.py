"""Account list / caller queue, account page, call logging and payments."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.money import to_paise
from app.models import PTP, Account, AllocationHistory, CallLog, Payment, Role, Status, User
from app.permissions import (
    assignable_callers, can_record_payment, can_work_account, get_visible_account,
)
from app.routers.common import filter_options, parse_filters, parse_date, query_without
from app.security import Forbidden, current_user
from app.services import accounts as account_service
from app.services.accounts import BUCKET_LABELS, PAGE_SIZE, queue_bucket
from app.services.calls import BY_CODE, DISPOSITIONS, CallError, default_followup, log_call
from app.services.payments import MODES, PaymentError, record_payment
from app.services.ptp import open_ptp
from app.web import flash, render

router = APIRouter()


@router.get("/accounts")
def account_list(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    filters = parse_filters(request.query_params)
    rows, total = account_service.search_accounts(db, user, filters)
    buckets = {}
    if rows:  # which queue bucket each visible row is in, for the "Why now" badge
        bucket_expr = queue_bucket(config.today())
        ids = [a.id for a in rows]
        buckets = dict(db.execute(select(Account.id, bucket_expr).where(Account.id.in_(ids))).all())
    callers = assignable_callers(db, user) if user.role != Role.CALLER else []
    return render(
        request, "accounts.html", user,
        rows=rows, total=total, filters=filters, page_size=PAGE_SIZE,
        pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        counts=account_service.queue_counts(db, user) if user.role == Role.CALLER else None,
        buckets=buckets, bucket_labels=BUCKET_LABELS, statuses=Status.ALL, callers=callers,
        qs_page=query_without(request, "page"), qs_sort=query_without(request, "sort", "page"),
        dispositions=BY_CODE, **filter_options(db),
    )


@router.get("/queue/next")
def queue_next(request: Request, after: int | None = None, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    nxt = account_service.next_in_queue(db, user, exclude_id=after)
    if nxt is None:
        flash(request, "Queue complete for today — every account has been worked. 🎉")
        return RedirectResponse("/accounts", status_code=303)
    return RedirectResponse(f"/accounts/{nxt.id}?from=queue", status_code=303)


def _load_account(db: Session, user: User, account_id: int):
    account = get_visible_account(db, user, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    return account


@router.get("/accounts/{account_id}")
def account_page(account_id: int, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    account = _load_account(db, user, account_id)
    calls = list(db.scalars(select(CallLog).where(CallLog.account_id == account.id)
                            .order_by(CallLog.created_at.desc(), CallLog.id.desc())))
    ptps = list(db.scalars(select(PTP).where(PTP.account_id == account.id)
                           .order_by(PTP.created_at.desc(), PTP.id.desc())))
    payments = list(db.scalars(select(Payment).where(Payment.account_id == account.id)
                               .order_by(Payment.payment_date.desc(), Payment.id.desc())))
    allocations = list(db.scalars(select(AllocationHistory).where(AllocationHistory.account_id == account.id)
                                  .order_by(AllocationHistory.allocated_at.desc(), AllocationHistory.id.desc())))

    timeline = (
        [("call", c.created_at, c) for c in calls]
        + [("payment", p.created_at, p) for p in payments]
        + [("allocation", a.allocated_at, a) for a in allocations]
    )
    timeline.sort(key=lambda item: item[1], reverse=True)

    today = config.today()
    return render(
        request, "account.html", user,
        a=account, calls=calls, ptps=ptps, payments=payments, allocations=allocations,
        timeline=timeline, open_ptp=open_ptp(db, account.id),
        dispositions=DISPOSITIONS, by_code=BY_CODE, modes=MODES,
        default_followups={d.code: default_followup(d.code, today).isoformat() for d in DISPOSITIONS},
        default_ptp_date=(today + timedelta(days=3)).isoformat(),
        max_ptp_date=(today + timedelta(days=90)).isoformat(),
        can_work=can_work_account(user, account) and not account.is_terminal,
        can_pay=can_record_payment(user) and not account.is_terminal,
        from_queue=request.query_params.get("from") == "queue" or user.role == Role.CALLER,
    )


@router.post("/accounts/{account_id}/calls")
def add_call(account_id: int, request: Request,
             disposition: str = Form(""), remarks: str = Form(""), next_followup: str = Form(""),
             ptp_amount: str = Form(""), ptp_date: str = Form(""), action: str = Form("save"),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    account = _load_account(db, user, account_id)
    if not can_work_account(user, account):
        raise Forbidden()
    try:
        amount = to_paise(ptp_amount) if disposition == "PTP" and ptp_amount else None
    except ValueError:
        amount = None
    try:
        log_call(db, account, user, disposition, remarks[:2000], parse_date(next_followup),
                 ptp_amount=amount, ptp_date=parse_date(ptp_date))
    except CallError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/accounts/{account_id}#log", status_code=303)

    label = BY_CODE[disposition].label
    flash(request, f"Call saved: {label} — {account.customer_name} ({account.loan_no}).")
    if action == "next":
        return RedirectResponse(f"/queue/next?after={account_id}", status_code=303)
    return RedirectResponse(f"/accounts/{account_id}", status_code=303)


@router.post("/accounts/{account_id}/payments")
def add_payment(account_id: int, request: Request,
                amount: str = Form(""), payment_date: str = Form(""), mode: str = Form(""),
                reference: str = Form(""), is_settlement: str = Form(""),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    account = _load_account(db, user, account_id)
    if not can_record_payment(user):
        raise Forbidden()
    try:
        paise = to_paise(amount)
        pay_date = parse_date(payment_date)
        if pay_date is None:
            raise PaymentError("Enter the payment date.")
        record_payment(db, account, user, paise, pay_date, mode, reference[:60],
                       is_settlement=is_settlement == "1")
    except (ValueError, PaymentError) as exc:
        message = str(exc) if isinstance(exc, PaymentError) else "Enter a valid amount."
        flash(request, message, "error")
        return RedirectResponse(f"/accounts/{account_id}#pay", status_code=303)
    flash(request, f"Payment recorded. Account is now {account.status}.")
    return RedirectResponse(f"/accounts/{account_id}", status_code=303)
