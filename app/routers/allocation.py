"""Allocation screen: pick accounts (by ticking or "all matching"), pick caller(s), assign."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import QueryParams
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account, Role, Status, User
from app.permissions import assignable_callers
from app.routers.common import filter_options, parse_filters, query_without
from app.security import require_roles
from app.services import accounts as account_service
from app.services.accounts import PAGE_SIZE
from app.services.allocation import AllocationError, allocate
from app.web import flash, render

router = APIRouter()
allocator = require_roles(Role.HEAD, Role.COO, Role.MANAGER)
MAX_BULK = 5000  # cap for "allocate all matching"


def _open_load(db: Session, caller_ids: list[int]) -> dict[int, int]:
    """Open (not closed/settled) accounts currently owned by each caller."""
    if not caller_ids:
        return {}
    rows = db.execute(
        select(Account.owner_id, func.count())
        .where(Account.owner_id.in_(caller_ids), Account.status.not_in(Status.TERMINAL))
        .group_by(Account.owner_id)
    ).all()
    return dict(rows)


def allocation_filters(params: QueryParams):
    filters = parse_filters(params, default_sort="balance")
    if "owner" not in params:
        filters.unallocated = True  # most common job: allocate fresh accounts
    return filters


@router.get("/allocation")
def allocation_page(request: Request, user: User = Depends(allocator), db: Session = Depends(get_db)):
    filters = allocation_filters(request.query_params)
    rows, total = account_service.search_accounts(db, user, filters)
    callers = assignable_callers(db, user)
    managers = {}
    for caller in callers:
        managers.setdefault(caller.manager.name if caller.manager else "—", []).append(caller)
    return render(
        request, "allocation.html", user,
        rows=rows, total=total, filters=filters, page_size=PAGE_SIZE, max_bulk=MAX_BULK,
        pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        callers=callers, teams=managers, load=_open_load(db, [c.id for c in callers]),
        statuses=[s for s in Status.ALL if s not in Status.TERMINAL],
        qs_page=query_without(request, "page"),
        **filter_options(db),
    )


@router.post("/allocation")
def allocate_accounts(request: Request, caller_ids: list[int] = Form([]), account_ids: list[int] = Form([]),
                      scope: str = Form("selected"), limit: int = Form(MAX_BULK),
                      note: str = Form(""), return_qs: str = Form(""),
                      user: User = Depends(allocator), db: Session = Depends(get_db)):
    back = "/allocation" + (f"?{return_qs}" if return_qs else "")
    if scope == "all":
        # Re-run the same filtered query server-side instead of trusting a long id list.
        filters = allocation_filters(QueryParams(return_qs))
        account_ids = account_service.matching_ids(db, user, filters, max(1, min(limit, MAX_BULK)))

    try:
        result = allocate(db, user, account_ids, caller_ids, note=note[:255])
    except AllocationError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(back, status_code=303)

    if len(caller_ids) == 1:
        who = next(c.name for c in assignable_callers(db, user) if c.id == caller_ids[0])
    else:
        who = f"{len(caller_ids)} callers (round-robin)"
    parts = [f"{result.moved:,} account(s) assigned to {who}"]
    if result.reassigned:
        parts.append(f"{result.reassigned:,} of them reassigned from another caller (history kept)")
    if result.unchanged:
        parts.append(f"{result.unchanged:,} already with that caller")
    if result.skipped_closed:
        parts.append(f"{result.skipped_closed:,} closed/settled skipped")
    flash(request, " · ".join(parts) + ".", "success" if result.moved else "info")
    return RedirectResponse(back, status_code=303)
