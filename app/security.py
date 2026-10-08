"""Password hashing and the "who is logged in" dependency.

Passwords are hashed with scrypt (Python stdlib, memory-hard) with a random
per-user salt. The session cookie only stores the user id and is signed with
SECRET_KEY, so it cannot be forged or edited by the browser.
"""
import base64
import hashlib
import hmac
import os

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return hmac.compare_digest(digest, expected)


class NotAuthenticated(Exception):
    """Raised when a page needs a login; handled by redirecting to /login."""


class Forbidden(Exception):
    """Raised when the logged-in user's role may not do this; rendered as 403."""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        request.session.clear()
        raise NotAuthenticated()
    return user


def require_roles(*roles: str):
    """Dependency factory: `Depends(require_roles(Role.HEAD, Role.MANAGER))`."""

    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user

    return checker
