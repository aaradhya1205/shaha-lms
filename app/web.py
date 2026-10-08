"""Template setup, formatting filters and flash messages."""
from datetime import date, datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import config
from app.config import BASE_DIR
from app.money import inr, rupees_input
from app.models import User
from app import permissions

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _fmt_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d %b %Y")


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d %b %Y, %I:%M %p")


def _relative_day(value: date | None) -> str:
    if value is None:
        return "—"
    delta = (value - config.today()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    return f"In {delta} days" if delta > 0 else f"{-delta} days ago"


def _indian_number(n: int | None) -> str:
    return inr((n or 0) * 100).lstrip("₹")


templates.env.filters.update(
    inr=inr, rupees_input=rupees_input, d=_fmt_date, dt=_fmt_dt, rel=_relative_day,
    num=_indian_number,
)
templates.env.globals.update(perm=permissions, today=config.today, show_demo_logins=config.SHOW_DEMO_LOGINS,
                             demo_password=config.DEMO_PASSWORD, current_year=lambda: config.today().year)


def flash(request: Request, message: str, kind: str = "success") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def render(request: Request, name: str, user: User | None = None, status_code: int = 200, **context):
    messages = request.session.pop("flash", []) if "session" in request.scope else []
    return templates.TemplateResponse(
        request, name, {"user": user, "messages": messages, **context}, status_code=status_code
    )
