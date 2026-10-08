"""Helpers shared by routers."""
from collections.abc import Mapping
from datetime import date
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Office
from app.services.accounts import SORTS, AccountFilters


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_filters(p: Mapping[str, str], default_sort: str = "priority") -> AccountFilters:
    sort = p.get("sort") or default_sort
    return AccountFilters(
        q=(p.get("q") or "")[:100],
        status=p.get("status") or "",
        office_id=_int(p.get("office")),
        product=p.get("product") or "",
        portfolio=p.get("portfolio") or "",
        owner_id=_int(p.get("owner")),
        unallocated=p.get("owner") == "none",
        batch_id=_int(p.get("batch")),
        view=p.get("view") or "",
        include_closed=p.get("closed") == "1",
        sort=sort if sort in SORTS else default_sort,
        page=_int(p.get("page")) or 1,
    )


def filter_options(db: Session) -> dict:
    return {
        "offices": list(db.scalars(select(Office).order_by(Office.name))),
        "portfolios": list(db.scalars(select(Account.portfolio).distinct().order_by(Account.portfolio))),
        "products": ["Personal Loan", "Credit Card"],
        "sorts": SORTS,
    }


def query_without(request: Request, *keys: str) -> str:
    """Current query string minus some keys (for pagination / sort links)."""
    items = [(k, v) for k, v in request.query_params.multi_items() if k not in keys and v != ""]
    return urlencode(items)
