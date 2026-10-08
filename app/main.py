"""FastAPI application: middleware, error handling and routers."""
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.config import ALLOWED_HOSTS, BASE_DIR, IS_PRODUCTION, SECRET_KEY
from app.db import Base, SessionLocal, engine
from app.routers import accounts, allocation, auth, dashboard, upload
from app.security import Forbidden, NotAuthenticated
from app.services.ptp import sweep_due, sweep_if_new_day
from app.web import render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lms")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    ),
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Shaha Finlease LMS", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def daily_ptp_sweep(request: Request, call_next):
    """Mark overdue promises Broken once per business day, before any page renders."""
    if sweep_due() and not request.url.path.startswith("/static"):
        with SessionLocal() as db:
            sweep_if_new_day(db)
    return await call_next(request)


@app.middleware("http")
async def security(request: Request, call_next):
    # CSRF defence: a state-changing request must come from our own pages.
    # Browsers send Origin on cross-site POSTs; SameSite=Lax cookies are the second layer.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        source = urlsplit(origin).netloc.lower() if origin else None
        own = {request.headers.get("host", "").lower(), request.headers.get("x-forwarded-host", "").lower()}
        if source and source not in own | ALLOWED_HOSTS:
            log.warning("Blocked cross-site %s %s from %s", request.method, request.url.path, origin)
            return PlainTextResponse("Cross-site request blocked.", status_code=403)
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not request.url.path.startswith("/static"):
        response.headers.setdefault("Cache-Control", "no-store")  # pages hold customer data
    return response


# Added last so it runs first: the session is available to everything above.
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, session_cookie="lms_session",
    max_age=12 * 60 * 60, same_site="lax", https_only=IS_PRODUCTION,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


@app.get("/healthz", include_in_schema=False)
def healthz():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return JSONResponse({"status": "ok"})


@app.exception_handler(NotAuthenticated)
async def _login_required(request: Request, _exc):
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, _exc):
    return render(request, "error.html", status_code=403, code=403, title="Access restricted",
                  message="Your role does not have access to this page.")


@app.exception_handler(404)
async def _not_found(request: Request, _exc):
    return render(request, "error.html", status_code=404, code=404, title="Page not found",
                  message="This page or account does not exist, or is not assigned to you.")


@app.exception_handler(Exception)
async def _server_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return render(request, "error.html", status_code=500, code=500, title="Something went wrong",
                  message="The error has been logged. Please try again, or contact support if it continues.")


for router in (auth.router, dashboard.router, accounts.router, upload.router, allocation.router):
    app.include_router(router)
