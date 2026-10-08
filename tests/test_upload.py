"""Feature 2: upload accounts from CSV (1,00,000 rows)."""
import io
import time

import pytest
from sqlalchemy import func, select

from app.models import Account, Status
from app.services.upload import UploadError, import_accounts
from tests.conftest import HEADER, login, make_csv


def test_valid_bad_and_duplicate_rows(db):
    batch = import_accounts(db, make_csv([
        "NEW001,Asha Patil,+91 98200 11111,Dadar,Credit Card,\"1,25,200\",150000",
        "NEW002,Bad Mobile,12345,Dadar,Credit Card,5000,5000",
        "NEW003,Bad Office,9820011112,Delhi,Credit Card,5000,5000",
        "NEW004,Bad Product,9820011113,Dadar,Home Loan,5000,5000",
        "NEW005,Bad Amount,9820011114,Dadar,Credit Card,abc,5000",
        "LNT00001,Already Exists,9820011115,Dadar,Credit Card,5000,5000",
        "NEW001,Dup In File,9820011116,Dadar,Credit Card,5000,5000",
    ]), "mixed.csv", None)
    assert (batch.total_rows, batch.inserted, batch.duplicates, batch.failed) == (7, 1, 2, 4)
    acct = db.scalars(select(Account).where(Account.loan_no == "NEW001")).one()
    assert acct.mobile == "9820011111" and acct.outstanding == 125200_00 and acct.status == Status.NEW
    assert acct.owner_id is None
    assert "unknown office" in batch.errors_csv


def test_missing_required_column_rejects_file(db):
    with pytest.raises(UploadError):
        import_accounts(db, io.BytesIO(b"loan_no,customer_name\nX1,Someone\n"), "bad.csv", None)


def test_upload_screen_end_to_end(client, db):
    login(client, "head")
    r = client.post("/upload", files={"file": ("new.csv", make_csv(["UP0001,Ravi Rao,9900000001,Bangalore,PL,9000,9000"]), "text/csv")})
    assert r.status_code == 200 and "Imported" in r.text
    assert db.scalar(select(func.count()).select_from(Account).where(Account.loan_no == "UP0001")) == 1


def test_one_lakh_rows_load(db):
    rows = (f"BIG{i:06d},Customer {i},9{i:09d},{('Jogeshwari', 'Dadar', 'Bangalore')[i % 3]},"
            f"Credit Card,{1000 + i},{1000 + i}" for i in range(100_000))
    stream = io.BytesIO((HEADER + "\n".join(rows) + "\n").encode())
    started = time.perf_counter()
    batch = import_accounts(db, stream, "big.csv", None)
    elapsed = time.perf_counter() - started
    assert batch.inserted == 100_000 and batch.failed == 0
    assert elapsed < 60, f"took {elapsed:.1f}s"
