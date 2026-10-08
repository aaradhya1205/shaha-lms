"""Row-level access rules. Every account read or write goes through here.

    Head / COO        -> all accounts, all offices
    Manager           -> accounts owned by their team's callers
                         + unallocated accounts of their office (so they can allocate them)
    Caller            -> only accounts they currently own
    Customer service  -> accounts of their office (look-up and payment entry)
"""
from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from app.models import Account, Role, User


def team_caller_ids(manager: User):
    return select(User.id).where(User.manager_id == manager.id, User.role == Role.CALLER)


def scope_accounts(stmt: Select, user: User) -> Select:
    """Restrict any SELECT over Account to the rows `user` may see."""
    if user.role in Role.GLOBAL:
        return stmt
    if user.role == Role.CALLER:
        return stmt.where(Account.owner_id == user.id)
    if user.role == Role.MANAGER:
        return stmt.where(
            or_(
                Account.owner_id.in_(team_caller_ids(user)),
                (Account.owner_id.is_(None)) & (Account.office_id == user.office_id),
            )
        )
    if user.role == Role.CUSTOMER_SERVICE:
        return stmt.where(Account.office_id == user.office_id)
    return stmt.where(false())


def get_visible_account(db: Session, user: User, account_id: int) -> Account | None:
    """Fetch one account only if `user` may see it (otherwise None -> 404)."""
    stmt = scope_accounts(select(Account).where(Account.id == account_id), user)
    return db.scalars(stmt).first()


def assignable_callers(db: Session, user: User) -> list[User]:
    """Callers this user may allocate accounts to."""
    stmt = select(User).where(User.role == Role.CALLER, User.is_active.is_(True))
    if user.role == Role.MANAGER:
        stmt = stmt.where(User.manager_id == user.id)
    elif user.role not in Role.GLOBAL:
        return []
    return list(db.scalars(stmt.order_by(User.code)))


def can_upload(user: User) -> bool:
    return user.role in Role.GLOBAL


def can_allocate(user: User) -> bool:
    return user.role in Role.GLOBAL or user.role == Role.MANAGER


def can_work_account(user: User, account: Account) -> bool:
    """Log calls / promises: the owning caller, or a supervisor who can see it."""
    if user.role == Role.CALLER:
        return account.owner_id == user.id
    return user.role in Role.GLOBAL or user.role == Role.MANAGER


def can_record_payment(user: User) -> bool:
    return user.role in {Role.HEAD, Role.COO, Role.MANAGER, Role.CALLER, Role.CUSTOMER_SERVICE}
