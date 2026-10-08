"""Runtime settings, read from environment variables.

APP_ENV=production turns on secure cookies, requires a real SECRET_KEY and
hides the demo-login helper on the sign-in page.
"""
import os
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'lms.db'}")
APP_ENV = os.getenv("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV == "production"

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
    SECRET_KEY = "dev-only-not-secret"

# Extra hostnames allowed to submit forms (e.g. a Netlify/custom domain proxying to this app).
ALLOWED_HOSTS = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()}

DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "Shaha@123")
SHOW_DEMO_LOGINS = os.getenv("SHOW_DEMO_LOGINS", "0" if IS_PRODUCTION else "1") == "1"

# Optional fixed "business date" (YYYY-MM-DD) so a demo can fast-forward time,
# e.g. LMS_TODAY=2026-10-20 to show promises turning Broken.
_FIXED_TODAY = os.getenv("LMS_TODAY")


def today() -> date:
    """The business date. Every date rule in the app goes through this."""
    if _FIXED_TODAY:
        return date.fromisoformat(_FIXED_TODAY)
    return date.today()


def now() -> datetime:
    """Local timestamp on the business date (keeps LMS_TODAY demos consistent)."""
    current = datetime.now()
    return datetime.combine(today(), current.time()) if _FIXED_TODAY else current
