"""Login / logout, with a simple lock-out after repeated failed attempts."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import verify_password
from app.web import render

router = APIRouter()

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
_failures: dict[str, deque] = defaultdict(deque)  # "ip|username" -> failure timestamps


def _locked(key: str) -> bool:
    attempts = _failures[key]
    while attempts and attempts[0] < time.monotonic() - WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= MAX_FAILURES


def _safe_next(target: str | None) -> str:
    # Only allow same-site relative paths (blocks open redirects like //evil.com).
    if target and target.startswith("/") and not target.startswith("//") and not target.startswith("/login"):
        return target
    return "/home"


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    if request.session.get("user_id"):
        return RedirectResponse("/home", status_code=303)
    return render(request, "login.html", next=next or "")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          next: str = Form(""), db: Session = Depends(get_db)):
    username = username.strip().lower()[:50]
    key = f"{request.client.host if request.client else '-'}|{username}"
    if _locked(key):
        return render(request, "login.html", status_code=429, next=next, username=username,
                      error="Too many failed attempts. Please wait 15 minutes and try again.")
    user = db.scalars(select(User).where(User.username == username)).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        _failures[key].append(time.monotonic())
        return render(request, "login.html", status_code=401, next=next,
                      username=username, error="Invalid username or password.")
    _failures.pop(key, None)
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
