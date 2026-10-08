"""Login / logout."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import verify_password
from app.web import render

router = APIRouter()


def _safe_next(target: str | None) -> str:
    # Only allow same-site relative paths (blocks open redirects like //evil.com).
    if target and target.startswith("/") and not target.startswith("//") and target != "/login":
        return target
    return "/"


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", next=next or "")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          next: str = Form(""), db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.username == username.strip().lower())).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return render(request, "login.html", status_code=401, next=next,
                      username=username, error="Invalid username or password.")
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
