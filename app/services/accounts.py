"""Account list: search, filters, sorting and the caller work-queue ordering."""
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app import config
from app.models import Account, Status, User
from app.permissions import scope_accounts

PAGE_SIZE = 50

SORTS = {
    "priority": "Work priority",
    "balance": "Balance (high → low)",
    "followup": "Next follow-up",
    "name": "Customer name",
    "loan": "Loan number",
    "recent": "Recently called",
}

# Queue buckets, in the order the caller should work them.
BUCKET_LABELS = {
    0: "PTP due today",
    1: "Follow-up today",
    2: "Overdue",
    3: "New",
    4: "Upcoming",
    9: "Closed",
}


@dataclass
class AccountFilters:
    q: str = ""
    status: str = ""
    office_id: int | None = None
    product: str = ""
    portfolio: str = ""
    owner_id: int | None = None
    unallocated: bool = False
    batch_id: int | None = None
    view: str = ""  # "", "due", "overdue", "ptp", "new"
    include_closed: bool = False
    sort: str = "priority"
    page: int = 1
    extra: dict = field(default_factory=dict)


def queue_bucket(today: date):
    """SQL expression: 0 = PTP due today ... 4 = upcoming, 9 = closed/settled."""
    return case(
        (Account.status.in_(Status.TERMINAL), 9),
        (Account.ptp_date == today, 0),
        (Account.next_followup_date == today, 1),
        (or_(Account.next_followup_date < today, Account.ptp_date < today), 2),
        (Account.call_count == 0, 3),
        else_=4,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def build_query(user: User, f: AccountFilters) -> Select:
    today = config.today()
    stmt = scope_accounts(select(Account), user)

    q = f.q.strip()
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        like = f"%{_escape_like(q)}%"
        conditions = [
            Account.customer_name.ilike(like, escape="\\"),
            Account.loan_no.ilike(like, escape="\\"),
        ]
        if len(digits) >= 3 and len(digits) >= len(q.replace(" ", "")) - 3:
            conditions.append(Account.mobile.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))

    if f.status:
        stmt = stmt.where(Account.status == f.status)
    elif not f.include_closed and not q:
        stmt = stmt.where(Account.status.not_in(Status.TERMINAL))
    if f.office_id:
        stmt = stmt.where(Account.office_id == f.office_id)
    if f.product:
        stmt = stmt.where(Account.product == f.product)
    if f.portfolio:
        stmt = stmt.where(Account.portfolio == f.portfolio)
    if f.batch_id:
        stmt = stmt.where(Account.batch_id == f.batch_id)
    if f.unallocated:
        stmt = stmt.where(Account.owner_id.is_(None))
    elif f.owner_id:
        stmt = stmt.where(Account.owner_id == f.owner_id)

    if f.view == "due":
        stmt = stmt.where(or_(Account.ptp_date == today, Account.next_followup_date == today))
    elif f.view == "overdue":
        stmt = stmt.where(or_(Account.next_followup_date < today, Account.ptp_date < today))
    elif f.view == "ptp":
        stmt = stmt.where(Account.ptp_date.is_not(None))
    elif f.view == "new":
        stmt = stmt.where(Account.call_count == 0)
    return stmt


def order_query(stmt: Select, sort: str) -> Select:
    today = config.today()
    balance = Account.outstanding - Account.total_paid
    if sort == "balance":
        return stmt.order_by(balance.desc(), Account.id)
    if sort == "followup":
        return stmt.order_by(Account.next_followup_date.is_(None), Account.next_followup_date, Account.id)
    if sort == "name":
        return stmt.order_by(Account.customer_name, Account.id)
    if sort == "loan":
        return stmt.order_by(Account.loan_no)
    if sort == "recent":
        return stmt.order_by(Account.last_call_at.is_(None), Account.last_call_at.desc(), Account.id)
    # Work priority: due promises & follow-ups first, then overdue, new, upcoming;
    # inside a bucket the earliest date, then the biggest balance.
    return stmt.order_by(
        queue_bucket(today),
        func.coalesce(Account.ptp_date, Account.next_followup_date),
        balance.desc(),
        Account.id,
    )


def search_accounts(db: Session, user: User, f: AccountFilters):
    stmt = build_query(user, f)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    page = max(f.page, 1)
    rows = db.scalars(
        order_query(stmt, f.sort).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)
    ).unique().all()
    return rows, total


def matching_ids(db: Session, user: User, f: AccountFilters, limit: int) -> list[int]:
    """IDs for "allocate all matching" (in work-priority order)."""
    stmt = order_query(build_query(user, f), f.sort).with_only_columns(Account.id).limit(limit)
    return list(db.scalars(stmt))


def queue_counts(db: Session, user: User) -> dict[str, int]:
    """Counters for the caller's queue header."""
    today = config.today()
    base = scope_accounts(select(Account.id), user).where(Account.status.not_in(Status.TERMINAL))

    def count(*conds) -> int:
        return db.scalar(select(func.count()).select_from(base.where(*conds).subquery()))

    return {
        "due": count(or_(Account.ptp_date == today, Account.next_followup_date == today)),
        "ptp_today": count(Account.ptp_date == today),
        "overdue": count(or_(Account.next_followup_date < today, Account.ptp_date < today)),
        "new": count(Account.call_count == 0),
        "open": count(),
        "worked_today": count(Account.last_call_at >= datetime.combine(today, time.min)),
    }


def next_in_queue(db: Session, user: User, exclude_id: int | None = None) -> Account | None:
    """Top of the queue that hasn't been called yet today - powers "Save & next"."""
    today = config.today()
    stmt = build_query(user, AccountFilters()).where(
        or_(Account.last_call_at.is_(None), Account.last_call_at < datetime.combine(today, time.min))
    )
    if exclude_id:
        stmt = stmt.where(Account.id != exclude_id)
    return db.scalars(order_query(stmt, "priority").limit(1)).first()
