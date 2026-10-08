"""Payment recording.

`Account.outstanding` is never changed: it is the amount bought from the bank.
Each payment adds to `Account.total_paid`, and the status becomes:
    Settled    - payment flagged as full & final settlement
    Closed     - total paid >= outstanding
    Part-paid  - anything less
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import config
from app.models import Account, Payment, Status, User
from app.services.ptp import apply_payment_to_ptp, close_open_ptp

MODES = ["UPI", "NEFT/IMPS", "Cash", "Cheque", "Payment Link", "Other"]


class PaymentError(Exception):
    pass


def record_payment(db: Session, account: Account, user: User, amount: int, payment_date: date,
                   mode: str, reference: str | None = None, is_settlement: bool = False) -> Payment:
    today = config.today()
    if account.is_terminal:
        raise PaymentError(f"Account is already {account.status}.")
    if amount <= 0:
        raise PaymentError("Amount must be greater than 0.")
    if amount > account.balance:
        raise PaymentError("Amount is more than the balance due.")
    if payment_date > today:
        raise PaymentError("Payment date cannot be in the future.")
    if payment_date < today - timedelta(days=365):
        raise PaymentError("Payment date is more than a year old.")
    if mode not in MODES:
        raise PaymentError("Choose a payment mode.")

    ptp = apply_payment_to_ptp(db, account, amount, payment_date)
    payment = Payment(account_id=account.id, recorded_by_id=user.id, ptp_id=ptp.id if ptp else None,
                      amount=amount, payment_date=payment_date, mode=mode,
                      reference=(reference or "").strip() or None, is_settlement=is_settlement)
    db.add(payment)

    account.total_paid += amount
    if is_settlement:
        account.status = Status.SETTLED
    elif account.total_paid >= account.outstanding:
        account.status = Status.CLOSED
    else:
        account.status = Status.PART_PAID

    if account.is_terminal:
        close_open_ptp(db, account)
        account.next_followup_date = None
    db.commit()
    return payment
