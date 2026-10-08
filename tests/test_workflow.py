"""Features 4, 5, 7, 8, 9: account page, allocation history, call log, PTP, payments."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import PTP, Account, AllocationHistory, CallLog, PTPStatus, Status
from app.services.allocation import allocate
from app.services.calls import CallError, log_call
from app.services.payments import PaymentError, record_payment
from app.services.ptp import sweep_broken
from tests.conftest import TODAY, account_in, login


@pytest.fixture
def owned(db, users):
    acct = account_in(db, "Jogeshwari")
    allocate(db, users["head"], [acct.id], [users["caller1"].id])
    db.refresh(acct)
    return acct


def test_bulk_allocate_round_robin(db, users):
    jog = [a for a in db.scalars(select(Account)) if a.office.name == "Jogeshwari"]
    result = allocate(db, users["manager1"], [a.id for a in jog], [users["caller1"].id, users["caller2"].id])
    assert result.allocated == len(jog)
    owners = [a.owner_id for a in jog]
    assert abs(owners.count(users["caller1"].id) - owners.count(users["caller2"].id)) <= 1


def test_reassign_keeps_history(db, users, owned):
    log_call(db, owned, users["caller1"], "RNR", "no answer", None)
    allocate(db, users["head"], [owned.id], [users["caller2"].id], note="leave cover")
    db.refresh(owned)
    assert owned.owner_id == users["caller2"].id
    moves = list(db.scalars(select(AllocationHistory).where(AllocationHistory.account_id == owned.id)
                            .order_by(AllocationHistory.id)))
    assert [(m.from_user_id, m.to_user_id) for m in moves] == [
        (None, users["caller1"].id), (users["caller1"].id, users["caller2"].id)]
    assert db.scalars(select(CallLog).where(CallLog.account_id == owned.id)).one().user_id == users["caller1"].id


def test_call_with_only_a_disposition_is_enough(client, db, owned):
    """The 3-click rule: disposition + Save; follow-up defaults from the disposition."""
    login(client, "caller1")
    r = client.post(f"/accounts/{owned.id}/calls", data={"disposition": "CALLBACK"}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(owned)
    assert owned.status == Status.WORKING
    assert owned.next_followup_date == TODAY + timedelta(days=1)
    assert owned.call_count == 1 and owned.last_disposition == "CALLBACK"


def test_save_and_next_moves_through_queue(client, db, users, owned):
    login(client, "caller1")
    r = client.post(f"/accounts/{owned.id}/calls", data={"disposition": "RNR", "action": "next"},
                    follow_redirects=False)
    assert r.headers["location"] == f"/queue/next?after={owned.id}"


def test_account_page_shows_everything(client, db, users, owned):
    log_call(db, owned, users["caller1"], "PTP", "will pay", None, ptp_amount=500_00, ptp_date=TODAY + timedelta(days=2))
    record_payment(db, owned, users["caller1"], 200_00, TODAY, "UPI", "UTR1")
    login(client, "caller1")
    html = client.get(f"/accounts/{owned.id}").text
    for text in (owned.customer_name, owned.loan_no, owned.mobile, "Promises to pay", "₹500", "Payments", "₹200", "UTR1",
                 "Allocated to"):
        assert text in html


def test_ptp_saved_then_kept_by_payment(db, users, owned):
    log_call(db, owned, users["caller1"], "PTP", None, None, ptp_amount=1000_00, ptp_date=TODAY + timedelta(days=5))
    ptp = db.scalars(select(PTP).where(PTP.account_id == owned.id)).one()
    assert (ptp.amount, ptp.status, owned.status, owned.next_followup_date) == (
        1000_00, PTPStatus.PENDING, Status.PTP, TODAY + timedelta(days=5))

    record_payment(db, owned, users["caller1"], 1000_00, TODAY, "UPI")
    db.refresh(ptp)
    assert ptp.status == PTPStatus.KEPT and owned.ptp_date is None and owned.status == Status.PART_PAID


def test_unpaid_ptp_becomes_broken_after_its_date(db, users, owned):
    log_call(db, owned, users["caller1"], "PTP", None, None, ptp_amount=1000_00, ptp_date=TODAY + timedelta(days=1))
    assert sweep_broken(db, TODAY + timedelta(days=1)) == 0  # due date itself: still pending
    assert sweep_broken(db, TODAY + timedelta(days=2)) == 1
    ptp = db.scalars(select(PTP).where(PTP.account_id == owned.id)).one()
    db.refresh(owned)
    assert ptp.status == PTPStatus.BROKEN
    assert owned.status == Status.WORKING and owned.next_followup_date == TODAY + timedelta(days=2)


def test_invalid_ptp_does_not_save_call(db, users, owned):
    with pytest.raises(CallError):
        log_call(db, owned, users["caller1"], "PTP", None, None, ptp_amount=1, ptp_date=TODAY - timedelta(days=1))
    assert db.scalars(select(CallLog).where(CallLog.account_id == owned.id)).first() is None


def test_payments_part_paid_then_closed(db, users, owned):
    outstanding = owned.outstanding
    record_payment(db, owned, users["caller1"], 1000_00, TODAY, "UPI")
    assert (owned.outstanding, owned.total_paid, owned.status) == (outstanding, 1000_00, Status.PART_PAID)
    record_payment(db, owned, users["caller1"], owned.balance, TODAY, "Cash")
    assert (owned.outstanding, owned.total_paid, owned.status) == (outstanding, outstanding, Status.CLOSED)
    with pytest.raises(PaymentError):
        record_payment(db, owned, users["caller1"], 1_00, TODAY, "UPI")


def test_settlement(db, users, owned):
    record_payment(db, owned, users["cs1"], owned.outstanding // 2, TODAY, "NEFT/IMPS", is_settlement=True)
    assert owned.status == Status.SETTLED and owned.total_paid == owned.outstanding // 2


def test_payment_validation(db, users, owned):
    for amount, day in ((0, TODAY), (owned.outstanding + 1, TODAY), (100, TODAY + timedelta(days=1))):
        with pytest.raises(PaymentError):
            record_payment(db, owned, users["caller1"], amount, day, "UPI")


def test_payment_via_screen(client, db, owned):
    login(client, "caller1")
    r = client.post(f"/accounts/{owned.id}/payments",
                    data={"amount": "2,500", "payment_date": TODAY.isoformat(), "mode": "UPI"}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(owned)
    assert owned.total_paid == 2500_00 and owned.status == Status.PART_PAID


def test_closed_account_rejects_calls(db, users, owned):
    record_payment(db, owned, users["caller1"], owned.outstanding, TODAY, "UPI")
    with pytest.raises(CallError):
        log_call(db, owned, users["caller1"], "RNR", None, None)
