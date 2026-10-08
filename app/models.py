"""Core tables: Office, User, Account, AllocationHistory, CallLog, PTP, Payment (+ UploadBatch).

Money is stored as integer paise (1 rupee = 100 paise) so totals never suffer
floating-point rounding. Templates format it back to rupees.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import now
from app.db import Base


class Role:
    HEAD = "head"
    COO = "coo"
    MANAGER = "manager"
    CALLER = "caller"
    CUSTOMER_SERVICE = "customer_service"

    # Roles that see every office.
    GLOBAL = {HEAD, COO}
    LABELS = {
        HEAD: "Head of Collections",
        COO: "COO",
        MANAGER: "Manager",
        CALLER: "Caller",
        CUSTOMER_SERVICE: "Customer Service",
    }


class Status:
    NEW = "New"
    WORKING = "Working"
    PTP = "PTP"
    PART_PAID = "Part-paid"
    CLOSED = "Closed"
    SETTLED = "Settled"

    ALL = [NEW, WORKING, PTP, PART_PAID, CLOSED, SETTLED]
    TERMINAL = {CLOSED, SETTLED}


class PTPStatus:
    PENDING = "Pending"
    KEPT = "Kept"
    BROKEN = "Broken"
    CANCELLED = "Cancelled"  # replaced by a newer promise


class Office(Base):
    __tablename__ = "offices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # e.g. C001, M01
    name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    office: Mapped[Office | None] = relationship(lazy="joined")
    manager: Mapped["User | None"] = relationship(remote_side=[id])

    @property
    def role_label(self) -> str:
        return Role.LABELS.get(self.role, self.role)


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    errors_csv: Mapped[str | None] = mapped_column(Text)  # full error report

    uploaded_by: Mapped[User | None] = relationship()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_no: Mapped[str] = mapped_column(String(30), unique=True)
    portfolio: Mapped[str] = mapped_column(String(30))
    seller_bank: Mapped[str] = mapped_column(String(100))
    customer_name: Mapped[str] = mapped_column(String(120), index=True)
    mobile: Mapped[str] = mapped_column(String(15), index=True)
    email: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(60))
    state: Mapped[str | None] = mapped_column(String(60))
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    language: Mapped[str | None] = mapped_column(String(30))
    product: Mapped[str] = mapped_column(String(30))
    original_amount: Mapped[int] = mapped_column(BigInteger)  # paise
    outstanding: Mapped[int] = mapped_column(BigInteger)  # paise, as loaded - never changes
    total_paid: Mapped[int] = mapped_column(BigInteger, default=0)  # paise
    npa_date: Mapped[date | None] = mapped_column(Date)
    last_payment_date: Mapped[date | None] = mapped_column(Date)  # as received from the bank
    status: Mapped[str] = mapped_column(String(20), default=Status.NEW, index=True)

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    allocated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Denormalised "work state" so the caller queue is one indexed query.
    next_followup_date: Mapped[date | None] = mapped_column(Date)
    ptp_date: Mapped[date | None] = mapped_column(Date)  # date of the open promise
    ptp_amount: Mapped[int | None] = mapped_column(BigInteger)  # paise
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_disposition: Mapped[str | None] = mapped_column(String(40))
    call_count: Mapped[int] = mapped_column(Integer, default=0)

    batch_id: Mapped[int | None] = mapped_column(ForeignKey("upload_batches.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    office: Mapped[Office] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_accounts_owner_status", "owner_id", "status"),
        Index("ix_accounts_office_owner", "office_id", "owner_id"),
    )

    @property
    def balance(self) -> int:
        return max(self.outstanding - self.total_paid, 0)

    @property
    def is_terminal(self) -> bool:
        return self.status in Status.TERMINAL


class AllocationHistory(Base):
    __tablename__ = "allocation_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    allocated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    allocated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    note: Mapped[str | None] = mapped_column(String(255))

    from_user: Mapped[User | None] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped[User] = relationship(foreign_keys=[to_user_id])
    allocated_by: Mapped[User] = relationship(foreign_keys=[allocated_by_id])


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    disposition: Mapped[str] = mapped_column(String(40))
    remarks: Mapped[str | None] = mapped_column(Text)
    next_followup_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    user: Mapped[User] = relationship()


class PTP(Base):
    __tablename__ = "ptps"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    call_log_id: Mapped[int | None] = mapped_column(ForeignKey("call_logs.id"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(BigInteger)  # paise
    promised_date: Mapped[date] = mapped_column(Date)
    paid_amount: Mapped[int] = mapped_column(BigInteger, default=0)  # paise paid towards this promise
    status: Mapped[str] = mapped_column(String(15), default=PTPStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_by: Mapped[User] = relationship()

    __table_args__ = (Index("ix_ptps_status_date", "status", "promised_date"),)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ptp_id: Mapped[int | None] = mapped_column(ForeignKey("ptps.id"))
    amount: Mapped[int] = mapped_column(BigInteger)  # paise
    payment_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str | None] = mapped_column(String(60))
    is_settlement: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    recorded_by: Mapped[User] = relationship()
