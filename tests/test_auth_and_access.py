"""Feature 1: login with role-based access, enforced on the server."""
from sqlalchemy import select

from app.models import Account
from app.services.allocation import AllocationError, allocate
from tests.conftest import account_in, login


def test_passwords_are_hashed(users):
    assert all(u.password_hash.startswith("scrypt$") and "Shaha@123" not in u.password_hash for u in users.values())


def test_bad_password_rejected(client, db):
    r = client.post("/login", data={"username": "head", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid username or password" in r.text


def test_pages_require_login(client, db):
    r = client.get("/accounts", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_login_redirect_is_not_an_open_redirect(client, db):
    r = client.post("/login", data={"username": "head", "password": "Shaha@123", "next": "//evil.example"},
                    follow_redirects=False)
    assert r.headers["location"] == "/home"


def test_caller_sees_only_own_accounts(client, db, users):
    mine = account_in(db, "Jogeshwari")
    other = db.scalars(select(Account).where(Account.id != mine.id, Account.office_id == mine.office_id)).first()
    allocate(db, users["head"], [mine.id], [users["caller1"].id])
    allocate(db, users["head"], [other.id], [users["caller2"].id])

    login(client, "caller1")
    page = client.get("/accounts?closed=1").text
    assert mine.loan_no in page and other.loan_no not in page
    assert client.get(f"/accounts/{mine.id}").status_code == 200
    # Direct URL to someone else's account -> 404, and writes are blocked too.
    assert client.get(f"/accounts/{other.id}").status_code == 404
    assert client.post(f"/accounts/{other.id}/calls", data={"disposition": "RNR"}).status_code == 404
    assert client.post(f"/accounts/{other.id}/payments", data={"amount": "100"}).status_code == 404


def test_caller_cannot_open_supervisor_screens(client, db):
    login(client, "caller1")
    for path in ("/upload", "/allocation", "/dashboard"):
        assert client.get(path).status_code == 403
    assert client.post("/allocation", data={"caller_ids": "1", "account_ids": "1"}).status_code == 403


def test_manager_sees_team_and_unallocated_office_accounts(client, db, users):
    jog = [a for a in db.scalars(select(Account)) if a.office.name == "Jogeshwari"]
    dadar = account_in(db, "Dadar")
    allocate(db, users["head"], [jog[0].id], [users["caller1"].id])   # manager1's team
    allocate(db, users["head"], [jog[1].id], [users["caller10"].id])  # manager2's team

    login(client, "manager1")
    assert client.get(f"/accounts/{jog[0].id}").status_code == 200   # own team
    assert client.get(f"/accounts/{jog[2].id}").status_code == 200   # unallocated, own office
    assert client.get(f"/accounts/{jog[1].id}").status_code == 404   # other manager's team
    assert client.get(f"/accounts/{dadar.id}").status_code == 404    # other office


def test_manager_can_only_allocate_to_own_team(db, users):
    acct = account_in(db, "Jogeshwari")
    try:
        allocate(db, users["manager1"], [acct.id], [users["caller10"].id])
        raise AssertionError("expected AllocationError")
    except AllocationError:
        pass


def test_head_sees_everything(client, db):
    login(client, "head")
    assert "of <b>30</b>" in client.get("/accounts").text


def test_upload_is_head_only(client, db):
    login(client, "manager1")
    assert client.get("/upload").status_code == 403


def test_signed_in_user_never_bounces_to_root(client, db):
    """On Netlify "/" is a static page, so the app must land users on /home, not "/"."""
    login(client, "caller1")
    assert client.get("/login", follow_redirects=False).headers["location"] == "/home"
    assert client.get("/home", follow_redirects=False).headers["location"] == "/accounts"
    r = client.post("/login", data={"username": "caller1", "password": "Shaha@123"}, follow_redirects=False)
    assert r.headers["location"] == "/home"
