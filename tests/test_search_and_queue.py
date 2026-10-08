"""Features 3 & 6: search by name / phone / loan number; caller queue ordering."""
from datetime import timedelta

from sqlalchemy import select

from app.models import Account
from app.services.accounts import AccountFilters, search_accounts
from app.services.allocation import allocate
from tests.conftest import TODAY


def _search(db, user, q):
    rows, total = search_accounts(db, user, AccountFilters(q=q))
    return [a.loan_no for a in rows]


def test_search_by_name_phone_and_loan(db, users):
    head = users["head"]
    assert _search(db, head, "Customer 7") == ["LNT00007"]
    assert _search(db, head, "lnt00012") == ["LNT00012"]
    assert _search(db, head, "9800000015") == ["LNT00015"]
    assert "LNT00015" in _search(db, head, "00015")  # partial number
    assert _search(db, head, "nobody") == []


def test_search_is_scoped_to_caller(db, users):
    assert _search(db, users["caller1"], "Customer 7") == []


def test_queue_puts_todays_promises_and_followups_first(db, users):
    caller = users["caller1"]
    accts = [a for a in db.scalars(select(Account).order_by(Account.id)) if a.office.name == "Jogeshwari"][:5]
    allocate(db, users["head"], [a.id for a in accts], [caller.id])
    upcoming, new, overdue, followup_today, ptp_today = accts
    upcoming.next_followup_date, upcoming.call_count = TODAY + timedelta(days=3), 1
    overdue.next_followup_date, overdue.call_count = TODAY - timedelta(days=2), 1
    followup_today.next_followup_date, followup_today.call_count = TODAY, 1
    ptp_today.ptp_date, ptp_today.ptp_amount, ptp_today.call_count = TODAY, 100, 1
    db.commit()

    rows, _ = search_accounts(db, caller, AccountFilters())
    assert [a.id for a in rows] == [ptp_today.id, followup_today.id, overdue.id, new.id, upcoming.id]
