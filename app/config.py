"""Runtime settings, read from environment variables with demo-friendly defaults."""
import os
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'lms.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "Shaha@123")

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
