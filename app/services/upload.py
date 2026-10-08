"""CSV account import, built for 1,00,000+ rows.

The file is streamed row by row, validated, and written with bulk
multi-row INSERTs in chunks, all in one transaction (a failed import
leaves nothing half-loaded). Bad rows are skipped and reported, so they
never block the good rows.
"""
import csv
import io
import time
from datetime import date, datetime
from typing import IO, Iterable

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app import config
from app.money import to_paise
from app.models import Account, Office, Status, UploadBatch, User

REQUIRED_COLUMNS = ["loan_no", "customer_name", "mobile", "office", "product", "outstanding"]
OPTIONAL_COLUMNS = [
    "portfolio", "seller_bank", "email", "city", "state", "language",
    "original_amount", "npa_date", "last_payment_date",
]
PRODUCTS = {
    "personal loan": "Personal Loan", "pl": "Personal Loan",
    "credit card": "Credit Card", "cc": "Credit Card",
}
CHUNK_SIZE = 5000
MAX_ERRORS_SHOWN = 100


class UploadError(Exception):
    """The file as a whole is unusable (e.g. required columns missing)."""


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid date {value!r} (use YYYY-MM-DD)")


def _parse_mobile(value: str) -> str:
    digits = "".join(ch for ch in value or "" if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        raise ValueError(f"mobile must have 10 digits, got {value!r}")
    return digits


def _amount(value: str, column: str) -> int:
    try:
        return to_paise(value)
    except ValueError:
        raise ValueError(f"{column} is not a number: {value!r}") from None


def _clean_row(raw: dict, offices: dict[str, int]) -> dict:
    """Validate one CSV row and map it to Account columns. Raises ValueError."""
    get = lambda key: (raw.get(key) or "").strip()  # noqa: E731

    loan_no = get("loan_no").upper()
    if not loan_no:
        raise ValueError("loan_no is empty")
    name = get("customer_name")
    if not name:
        raise ValueError("customer_name is empty")
    office_id = offices.get(get("office").lower())
    if office_id is None:
        raise ValueError(f"unknown office {get('office')!r}")
    product = PRODUCTS.get(get("product").lower())
    if product is None:
        raise ValueError(f"product must be Personal Loan or Credit Card, got {get('product')!r}")
    outstanding = _amount(get("outstanding"), "outstanding")
    if outstanding <= 0:
        raise ValueError("outstanding must be greater than 0")
    original = _amount(get("original_amount"), "original_amount") if get("original_amount") else outstanding

    return {
        "loan_no": loan_no,
        "portfolio": get("portfolio") or "-",
        "seller_bank": get("seller_bank") or "-",
        "customer_name": name,
        "mobile": _parse_mobile(get("mobile")),
        "email": get("email") or None,
        "city": get("city") or None,
        "state": get("state") or None,
        "office_id": office_id,
        "language": get("language") or None,
        "product": product,
        "original_amount": original,
        "outstanding": outstanding,
        "npa_date": _parse_date(get("npa_date")),
        "last_payment_date": _parse_date(get("last_payment_date")),
    }


def import_accounts(db: Session, stream: IO[bytes] | Iterable[str], filename: str,
                    uploaded_by: User | None) -> UploadBatch:
    started = time.perf_counter()
    text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="") if hasattr(stream, "read") else stream
    reader = csv.DictReader(text)

    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise UploadError(f"Missing required column(s): {', '.join(missing)}")
    reader.fieldnames = header  # normalised header names

    offices = {o.name.lower(): o.id for o in db.scalars(select(Office))}
    existing = set(db.scalars(select(Account.loan_no)))
    batch = UploadBatch(filename=filename, uploaded_by_id=uploaded_by.id if uploaded_by else None)
    db.add(batch)
    db.flush()

    now = config.now()
    pending: list[dict] = []
    errors: list[tuple[int, str, str]] = []
    total = inserted = duplicates = 0

    def flush_pending():
        nonlocal inserted
        if pending:
            db.execute(insert(Account), pending)
            inserted += len(pending)
            pending.clear()

    for line_no, raw in enumerate(reader, start=2):  # line 1 is the header
        total += 1
        try:
            row = _clean_row(raw, offices)
        except ValueError as exc:
            errors.append((line_no, (raw.get("loan_no") or "").strip(), str(exc)))
            continue
        if row["loan_no"] in existing:
            duplicates += 1
            continue
        existing.add(row["loan_no"])
        row.update(status=Status.NEW, total_paid=0, call_count=0, batch_id=batch.id, created_at=now)
        pending.append(row)
        if len(pending) >= CHUNK_SIZE:
            flush_pending()
    flush_pending()

    batch.total_rows, batch.inserted = total, inserted
    batch.duplicates, batch.failed = duplicates, len(errors)
    if errors:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["line", "loan_no", "error"])
        writer.writerows(errors)
        batch.errors_csv = out.getvalue()
    batch.duration_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    return batch


def first_errors(batch: UploadBatch, limit: int = MAX_ERRORS_SHOWN) -> list[list[str]]:
    if not batch.errors_csv:
        return []
    rows = list(csv.reader(io.StringIO(batch.errors_csv)))[1:]
    return rows[:limit]
