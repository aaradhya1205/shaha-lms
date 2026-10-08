"""Reset the demo database in one command.

    python -m app.seed                 # users + 10,000 accounts + realistic recent activity
    python -m app.seed --no-activity   # users + 10,000 fresh, unallocated accounts

Steps: drop & recreate tables -> 3 offices -> 73 users from data/users_seed.csv
(hashed passwords) -> accounts through the same CSV importer the Upload screen
uses -> optionally ~70% allocated with two weeks of calls, promises and payments.
"""
import argparse
import csv
import random
import time as clock
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app import config
from app.config import BASE_DIR
from app.db import Base, SessionLocal, engine
from app.models import PTP, Account, AllocationHistory, CallLog, Office, Payment, PTPStatus, Role, Status, User
from app.security import hash_password
from app.services.calls import BY_CODE
from app.services.payments import MODES
from app.services.ptp import sweep_broken
from app.services.upload import import_accounts

USERS_CSV = BASE_DIR / "data" / "users_seed.csv"
ACCOUNTS_CSV = BASE_DIR / "data" / "accounts_10000.csv"
OFFICES = ["Jogeshwari", "Dadar", "Bangalore"]
DEFAULT_USERNAMES = {"head": "head", "coo": "coo"}
ALLOCATED_SHARE = 0.70  # leave ~30% unallocated so the allocation demo has work


def seed_users(db) -> dict[str, User]:
    offices = {name: Office(name=name) for name in OFFICES}
    db.add_all(offices.values())
    db.flush()

    rows = list(csv.DictReader(open(USERS_CSV, encoding="utf-8")))
    users: dict[str, User] = {}
    for row in rows:  # managers appear before their callers in the file
        username = (row["username"] or DEFAULT_USERNAMES.get(row["role"], row["user_id"])).lower()
        manager = users.get(row["manager_id"]) if row["manager_id"] else None
        user = User(
            code=row["user_id"], name=row["name"], username=username,
            password_hash=hash_password(config.DEMO_PASSWORD), role=row["role"],
            office_id=offices[row["office"]].id if row["office"] in offices else None,
            manager_id=manager.id if manager else None,
        )
        db.add(user)
        db.flush()
        users[row["user_id"]] = user
    db.commit()
    return users


def _at(day, rng: random.Random) -> datetime:
    """A random working-hours timestamp on `day`."""
    return datetime.combine(day, time(9, 30)) + timedelta(minutes=rng.randint(0, 8 * 60))


def seed_activity(db, users: dict[str, User], rng: random.Random) -> None:
    """Allocate most accounts to callers of the same office and simulate the last 14 days."""
    today = config.today()
    head = users["U001"]
    callers_by_office: dict[int, list[User]] = {}
    for u in users.values():
        if u.role == Role.CALLER:
            callers_by_office.setdefault(u.office_id, []).append(u)

    accounts = list(db.scalars(select(Account).order_by(Account.id)))
    rng.shuffle(accounts)
    to_allocate = accounts[: int(len(accounts) * ALLOCATED_SHARE)]
    per_office_index: dict[int, int] = {}
    alloc_day = today - timedelta(days=14)

    calls, ptps, payments, history = [], [], [], []
    for account in to_allocate:
        team = callers_by_office[account.office_id]
        i = per_office_index.get(account.office_id, 0)
        per_office_index[account.office_id] = i + 1
        caller = team[i % len(team)]
        allocated_at = _at(alloc_day, rng)
        account.owner_id, account.allocated_at = caller.id, allocated_at
        history.append(AllocationHistory(account_id=account.id, to_user_id=caller.id,
                                         allocated_by_id=head.id, allocated_at=allocated_at,
                                         note="Initial allocation"))

        roll = rng.random()
        if roll < 0.40:
            continue  # allocated, not yet called -> "New"

        # 1-4 past calls on distinct days in the last 13 days.
        n_calls = rng.randint(1, 4)
        days = sorted(rng.sample(range(1, 14), n_calls), reverse=True)
        neutral = ["RNR", "SWITCHED_OFF", "CALLBACK", "RNR", "REFUSED", "DISPUTE", "SETTLEMENT"]
        for d in days[:-1]:
            day = today - timedelta(days=d)
            code = rng.choice(neutral)
            calls.append(CallLog(account_id=account.id, user_id=caller.id, disposition=code,
                                 remarks=None, created_at=_at(day, rng),
                                 next_followup_date=day + timedelta(days=BY_CODE[code].followup_days)))
        last_day = today - timedelta(days=days[-1])
        last_at = _at(last_day, rng)
        balance = account.outstanding

        outcome = rng.random()
        status, followup, ptp_obj = Status.WORKING, None, None
        if outcome < 0.30:  # promise to pay
            code = "PTP"
            amount = round(balance * rng.choice([0.1, 0.2, 0.25, 0.5, 1.0]) / 100_00) * 100_00 or balance
            amount = min(amount, balance)
            ptp_date = last_day + timedelta(days=rng.randint(1, 15))
            if rng.random() < 0.2:
                ptp_date = today  # make sure every caller has promises falling due today
            ptp_obj = PTP(account_id=account.id, created_by_id=caller.id, amount=amount,
                          promised_date=ptp_date, created_at=last_at)
            pay_roll = rng.random()
            if ptp_date <= today and pay_roll < 0.45:  # kept: paid on/before the date
                pay_day = min(ptp_date, today) - timedelta(days=rng.randint(0, 2))
                pay_day = max(pay_day, last_day)
                ptp_obj.status, ptp_obj.paid_amount = PTPStatus.KEPT, amount
                ptp_obj.resolved_at = _at(pay_day, rng)
                payments.append((account, Payment(account_id=account.id, recorded_by_id=caller.id,
                                                  amount=amount, payment_date=pay_day, mode=rng.choice(MODES[:3]),
                                                  reference=f"UTR{rng.randint(10**9, 10**10 - 1)}",
                                                  created_at=_at(pay_day, rng)), ptp_obj))
                status = Status.CLOSED if amount >= balance else Status.PART_PAID
                followup = None if status == Status.CLOSED else pay_day + timedelta(days=rng.randint(3, 20))
            else:  # still pending (sweep marks past ones Broken)
                account.ptp_date, account.ptp_amount = ptp_date, amount
                status, followup = Status.PTP, ptp_date
        elif outcome < 0.36:  # settled
            code = "SETTLEMENT"
            amount = round(balance * rng.uniform(0.35, 0.6) / 100) * 100
            pay_day = min(last_day + timedelta(days=rng.randint(0, 3)), today)
            payments.append((account, Payment(account_id=account.id, recorded_by_id=caller.id, amount=amount,
                                              payment_date=pay_day, mode="NEFT/IMPS", is_settlement=True,
                                              reference=f"SET{rng.randint(10**7, 10**8 - 1)}",
                                              created_at=_at(pay_day, rng)), None))
            status = Status.SETTLED
        else:
            code = rng.choice(neutral)
            # Spread follow-ups so every caller has some due today, some overdue, some upcoming.
            followup = today + timedelta(days=rng.choice([-3, -2, -1, 0, 0, 0, 1, 2, 3, 5]))
            followup = max(followup, last_day + timedelta(days=1))

        calls.append(CallLog(account_id=account.id, user_id=caller.id, disposition=code, created_at=last_at,
                             next_followup_date=followup,
                             remarks=rng.choice([None, "Customer asked to call in the evening.",
                                                 "Spoke to spouse, will inform customer.",
                                                 "Salary expected next week.", "Requested settlement letter.",
                                                 "Says loan was with old bank, explained assignment."])))
        if ptp_obj:
            ptps.append(ptp_obj)
        account.status = status
        account.next_followup_date = followup
        account.call_count = n_calls
        account.last_call_at = last_at
        account.last_disposition = code

    db.add_all(history)
    db.add_all(calls)
    db.add_all(ptps)
    db.flush()
    for account, payment, ptp_obj in payments:
        payment.ptp_id = ptp_obj.id if ptp_obj else None
        account.total_paid += payment.amount
        db.add(payment)
    db.commit()
    broken = sweep_broken(db, today)
    print(f"  activity: {len(history):,} allocations, {len(calls):,} calls, {len(ptps):,} promises "
          f"({broken:,} now Broken), {len(payments):,} payments")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the LMS demo database.")
    parser.add_argument("--no-activity", action="store_true", help="only users + unallocated accounts")
    parser.add_argument("--accounts", default=str(ACCOUNTS_CSV), help="accounts CSV to load")
    parser.add_argument("--seed", type=int, default=42, help="random seed for simulated activity")
    parser.add_argument("--if-empty", action="store_true", help="only seed when the database has no users")
    args = parser.parse_args()

    if args.if_empty:
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            if db.scalar(select(User.id).limit(1)) is not None:
                print("Database already seeded - skipping.")
                return

    started = clock.perf_counter()
    print(f"Resetting database: {engine.url.render_as_string(hide_password=True)}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        users = seed_users(db)
        print(f"  users: {len(users)} (3 offices; password for all: {config.DEMO_PASSWORD})")
        with open(args.accounts, "rb") as fh:
            batch = import_accounts(db, fh, "accounts_10000.csv (seed)", uploaded_by=None)
        print(f"  accounts: {batch.inserted:,} imported in {batch.duration_ms / 1000:.1f}s")
        if not args.no_activity:
            seed_activity(db, users, random.Random(args.seed))
    print(f"Done in {clock.perf_counter() - started:.1f}s. Business date: {config.today()}")


if __name__ == "__main__":
    main()
