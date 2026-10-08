"""Production hardening: headers, CSRF origin check, login lock-out, health check."""
from app.routers import auth
from tests.conftest import login


def test_security_headers(client, db):
    r = client.get("/login")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_cross_site_post_is_blocked(client, db):
    login(client, "caller1")
    r = client.post("/logout", headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_site_post_is_allowed(client, db):
    login(client, "caller1")
    r = client.post("/logout", headers={"origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 303


def test_login_locks_after_repeated_failures(client, db):
    auth._failures.clear()
    for _ in range(auth.MAX_FAILURES):
        assert client.post("/login", data={"username": "caller5", "password": "nope"}).status_code == 401
    r = client.post("/login", data={"username": "caller5", "password": "Shaha@123"})
    assert r.status_code == 429
    auth._failures.clear()


def test_healthz(client, db):
    assert client.get("/healthz").json() == {"status": "ok"}
