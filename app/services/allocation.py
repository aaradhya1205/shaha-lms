"""Allocate / reassign accounts to callers.

Re-allocation only changes `Account.owner_id`; every move is appended to
AllocationHistory, and call logs, promises and payments stay attached to the
account, so the full history follows the account to its new caller.
"""
from dataclasses import dataclass
from itertools import cycle

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Account, AllocationHistory, User
from app.permissions import assignable_callers, scope_accounts

CHUNK = 900  # stay well under SQL parameter limits for IN (...)


class AllocationError(Exception):
    pass


@dataclass
class AllocationResult:
    allocated: int = 0
    reassigned: int = 0
    unchanged: int = 0
    skipped_closed: int = 0
    not_visible: int = 0

    @property
    def moved(self) -> int:
        return self.allocated + self.reassigned


def allocate(db: Session, actor: User, account_ids: list[int], caller_ids: list[int],
             note: str | None = None) -> AllocationResult:
    """Assign accounts to one caller, or spread them round-robin over several."""
    allowed = {c.id: c for c in assignable_callers(db, actor)}
    callers = [allowed[cid] for cid in dict.fromkeys(caller_ids) if cid in allowed]
    if not callers or len(callers) != len(set(caller_ids)):
        raise AllocationError("You can only allocate to callers in your team.")
    account_ids = list(dict.fromkeys(account_ids))
    if not account_ids:
        raise AllocationError("Select at least one account.")

    result = AllocationResult()
    now = config.now()
    next_caller = cycle(callers)
    seen = 0
    for start in range(0, len(account_ids), CHUNK):
        chunk = account_ids[start:start + CHUNK]
        stmt = scope_accounts(select(Account).where(Account.id.in_(chunk)), actor).order_by(Account.id)
        accounts = list(db.scalars(stmt))
        seen += len(accounts)
        history = []
        for account in accounts:
            if account.is_terminal:
                result.skipped_closed += 1
                continue
            caller = next(next_caller)
            if account.owner_id == caller.id:
                result.unchanged += 1
                continue
            if account.owner_id is None:
                result.allocated += 1
            else:
                result.reassigned += 1
            history.append(AllocationHistory(
                account_id=account.id, from_user_id=account.owner_id, to_user_id=caller.id,
                allocated_by_id=actor.id, allocated_at=now, note=note or None,
            ))
            account.owner_id = caller.id
            account.allocated_at = now
        db.add_all(history)
    result.not_visible = len(account_ids) - seen
    db.commit()
    return result
