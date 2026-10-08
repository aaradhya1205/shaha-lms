"""Promise-to-pay rules.

* One open (Pending) promise per account; a new promise cancels the old one.
* Payments dated on/before the promised date count towards it; once the
  promised amount is covered the promise is Kept.
* A promise still Pending after its date is marked Broken by `sweep_broken`,
  and the account jumps back to the top of the caller's queue.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import PTP, Account, PTPStatus, Status, User


class PTPError(Exception):
    pass


def open_ptp(db: Session, account_id: int) -> PTP | None:
    return db.scalars(
        select(PTP).where(PTP.account_id == account_id, PTP.status == PTPStatus.PENDING)
    ).first()


def create_ptp(db: Session, account: Account, user: User, amount: int, promised_date: date,
               call_log_id: int | None = None) -> PTP:
    """Validate and add a promise (caller commits the transaction)."""
    today = config.today()
    if account.is_terminal:
        raise PTPError(f"Account is {account.status}; no new promises.")
    if amount <= 0:
        raise PTPError("Promise amount must be greater than 0.")
    if amount > account.balance:
        raise PTPError("Promise amount cannot be more than the balance due.")
    if promised_date < today:
        raise PTPError("Promise date cannot be in the past.")
    if (promised_date - today).days > 90:
        raise PTPError("Promise date must be within 90 days.")

    previous = open_ptp(db, account.id)
    if previous:
        previous.status = PTPStatus.CANCELLED
        previous.resolved_at = config.now()

    ptp = PTP(account_id=account.id, call_log_id=call_log_id, created_by_id=user.id,
              amount=amount, promised_date=promised_date)
    db.add(ptp)
    account.ptp_date, account.ptp_amount = promised_date, amount
    account.status = Status.PTP
    account.next_followup_date = promised_date  # chase on the promise day
    return ptp


def _after_ptp_closed(account: Account) -> None:
    account.ptp_date = None
    account.ptp_amount = None


def apply_payment_to_ptp(db: Session, account: Account, amount: int, payment_date: date) -> PTP | None:
    """Credit a payment against the open promise; returns the promise it counted towards."""
    ptp = open_ptp(db, account.id)
    if ptp is None or payment_date > ptp.promised_date:
        return None
    ptp.paid_amount += amount
    if ptp.paid_amount >= ptp.amount:
        ptp.status = PTPStatus.KEPT
        ptp.resolved_at = config.now()
        _after_ptp_closed(account)
    return ptp


def close_open_ptp(db: Session, account: Account) -> None:
    """Account closed or settled: the open promise is fulfilled by definition."""
    ptp = open_ptp(db, account.id)
    if ptp:
        ptp.status = PTPStatus.KEPT
        ptp.resolved_at = config.now()
    _after_ptp_closed(account)


def sweep_broken(db: Session, today: date | None = None) -> int:
    """Mark every Pending promise whose date has passed as Broken. Idempotent."""
    today = today or config.today()
    overdue = list(db.scalars(
        select(PTP).where(PTP.status == PTPStatus.PENDING, PTP.promised_date < today)
    ))
    now = config.now()
    for ptp in overdue:
        ptp.status = PTPStatus.BROKEN
        ptp.resolved_at = now
        account = db.get(Account, ptp.account_id)
        _after_ptp_closed(account)
        if account.status == Status.PTP:
            account.status = Status.PART_PAID if account.total_paid > 0 else Status.WORKING
        if not account.is_terminal:
            account.next_followup_date = today  # back to the top of today's queue
    db.commit()
    return len(overdue)


_last_sweep: date | None = None


def sweep_due() -> bool:
    return _last_sweep != config.today()


def sweep_if_new_day(db: Session) -> None:
    """Cheap guard called per request: run the sweep once per business date."""
    global _last_sweep
    today = config.today()
    if _last_sweep != today:
        sweep_broken(db, today)
        _last_sweep = today
