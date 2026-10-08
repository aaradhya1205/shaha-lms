"""Test setup: a throw-away SQLite database, real users from the seed file, a small account book."""
import io
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app import config  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PTP, Account, AllocationHistory, CallLog, Payment, UploadBatch, User  # noqa: E402
from app.seed import seed_users  # noqa: E402
from app.services import ptp as ptp_service  # noqa: E402
from app.services.upload import import_accounts  # noqa: E402

TODAY = date(2026, 10, 8)
PASSWORD = config.DEMO_PASSWORD
HEADER = "loan_no,customer_name,mobile,office,product,outstanding,original_amount\n"


def make_csv(rows: list[str]) -> io.BytesIO:
    return io.BytesIO((HEADER + "\n".join(rows) + "\n").encode())


def sample_rows(n: int = 30) -> list[str]:
    offices = ["Jogeshwari", "Dadar", "Bangalore"]
    return [f"LNT{i:05d},Customer {i},98{i:08d},{offices[i % 3]},Personal Loan,{10000 + i * 100},{10000 + i * 100}"
            for i in range(n)]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_users(db)
    yield


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(config, "_FIXED_TODAY", TODAY.isoformat())
    ptp_service._last_sweep = None


@pytest.fixture
def db():
    with SessionLocal() as session:
        for model in (Payment, PTP, CallLog, AllocationHistory, Account, UploadBatch):
            session.execute(delete(model))
        session.commit()
        import_accounts(session, make_csv(sample_rows()), "test.csv", None)
        yield session


@pytest.fixture
def users(db):
    return {u.username: u for u in db.scalars(select(User))}


@pytest.fixture
def client():
    return TestClient(app)


def login(client: TestClient, username: str) -> TestClient:
    client.cookies.clear()
    r = client.post("/login", data={"username": username, "password": PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def account_in(db, office: str) -> Account:
    return next(a for a in db.scalars(select(Account).order_by(Account.id)) if a.office.name == office)
