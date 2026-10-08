"""FastAPI application: middleware, error handling and routers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import BASE_DIR, SECRET_KEY
from app.db import Base, SessionLocal, engine
from app.routers import accounts, allocation, auth, dashboard, upload
from app.security import Forbidden, NotAuthenticated
from app.services.ptp import sweep_due, sweep_if_new_day
from app.web import render


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Shaha Finlease LMS", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def daily_ptp_sweep(request: Request, call_next):
    """Mark overdue promises Broken once per business day, before any page renders."""
    if sweep_due() and not request.url.path.startswith("/static"):
        with SessionLocal() as db:
            sweep_if_new_day(db)
    return await call_next(request)


# Added last so it runs first: the session is available to everything above.
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, session_cookie="lms_session",
    max_age=12 * 60 * 60, same_site="lax", https_only=False,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


@app.exception_handler(NotAuthenticated)
async def _login_required(request: Request, _exc):
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, _exc):
    return render(request, "error.html", status_code=403, code=403, title="Not allowed",
                  message="Your role does not have access to this page.")


@app.exception_handler(404)
async def _not_found(request: Request, _exc):
    return render(request, "error.html", status_code=404, code=404, title="Not found",
                  message="This page or account does not exist, or is not assigned to you.")


for router in (auth.router, dashboard.router, accounts.router, upload.router, allocation.router):
    app.include_router(router)
