"""Call logging. One call = disposition + optional remarks + next follow-up."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import config
from app.models import Account, CallLog, Status, User
from app.services.ptp import PTPError, create_ptp


@dataclass(frozen=True)
class Disposition:
    code: str
    label: str
    followup_days: int  # default next follow-up, in days from today
    tone: str  # used for colour in the UI: good / neutral / bad


DISPOSITIONS = [
    Disposition("PTP", "Promise to Pay", 0, "good"),
    Disposition("CALLBACK", "Call Back", 1, "neutral"),
    Disposition("RNR", "Ringing, No Response", 1, "neutral"),
    Disposition("SWITCHED_OFF", "Switched Off", 1, "neutral"),
    Disposition("SETTLEMENT", "Wants Settlement", 2, "good"),
    Disposition("PAID_CLAIM", "Claims Already Paid", 2, "neutral"),
    Disposition("REFUSED", "Refused to Pay", 3, "bad"),
    Disposition("DISPUTE", "Dispute", 7, "bad"),
    Disposition("WRONG_NUMBER", "Wrong Number", 7, "bad"),
]
BY_CODE = {d.code: d for d in DISPOSITIONS}


class CallError(Exception):
    pass


def default_followup(code: str, today: date | None = None) -> date:
    today = today or config.today()
    return today + timedelta(days=BY_CODE[code].followup_days)


def log_call(db: Session, account: Account, user: User, disposition: str, remarks: str | None,
             next_followup: date | None, ptp_amount: int | None = None,
             ptp_date: date | None = None) -> CallLog:
    if disposition not in BY_CODE:
        raise CallError("Choose a disposition.")
    if account.is_terminal:
        raise CallError(f"Account is {account.status}; no further calls are needed.")
    today = config.today()
    if disposition == "PTP":
        if not ptp_amount or not ptp_date:
            raise CallError("Promise to Pay needs an amount and a date.")
        next_followup = ptp_date
    next_followup = next_followup or default_followup(disposition, today)
    if next_followup < today:
        raise CallError("Next follow-up cannot be in the past.")

    call = CallLog(account_id=account.id, user_id=user.id, disposition=disposition,
                   remarks=(remarks or "").strip() or None, next_followup_date=next_followup)
    db.add(call)
    db.flush()  # get call.id for the promise link

    account.call_count += 1
    account.last_call_at = config.now()
    account.last_disposition = disposition
    if not account.is_terminal:
        account.next_followup_date = next_followup
        if account.status == Status.NEW:
            account.status = Status.WORKING
    if disposition == "PTP":
        try:
            create_ptp(db, account, user, ptp_amount, ptp_date, call_log_id=call.id)
        except PTPError as exc:
            db.rollback()  # the call is not saved without its valid promise
            raise CallError(str(exc)) from exc
    db.commit()
    return call
