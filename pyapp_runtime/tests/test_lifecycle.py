"""Tests for pyapp_runtime.lifecycle: attach() + server reference management."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pyapp_runtime.lifecycle as lifecycle
from pyapp_runtime import attach, get_server, set_server


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level state between tests."""
    yield
    lifecycle._server_ref = None
    lifecycle._attached_apps.clear()


def _route_paths(app: FastAPI) -> set[str]:
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_attach_registers_three_endpoints():
    app = FastAPI()
    before = _route_paths(app)
    attach(app)
    after = _route_paths(app)
    new_routes = after - before
    assert new_routes == {"/api/shutdown", "/api/health", "/api/restart"}


def test_attach_is_idempotent():
    """Calling attach twice on the same app must not duplicate routes."""
    app = FastAPI()
    attach(app)
    route_count_after_first = len(_route_paths(app))
    attach(app)
    route_count_after_second = len(_route_paths(app))
    assert route_count_after_first == route_count_after_second


def test_attach_returns_app_for_chaining():
    app = FastAPI()
    returned = attach(app)
    assert returned is app


def test_attach_different_apps_independently():
    app1 = FastAPI()
    app2 = FastAPI()
    attach(app1)
    attach(app2)
    assert "/api/shutdown" in _route_paths(app1)
    assert "/api/shutdown" in _route_paths(app2)


def test_set_and_get_server_roundtrip():
    class FakeServer:
        def __init__(self):
            self.should_exit = False

    server = FakeServer()
    set_server(server)
    assert get_server() is server


def test_get_server_returns_none_by_default():
    assert get_server() is None


def test_shutdown_endpoint_returns_500_when_server_not_registered():
    app = FastAPI()
    attach(app)
    with TestClient(app) as client:
        resp = client.post("/api/shutdown")
    assert resp.status_code == 500
    assert resp.json()["status"] == "error"


def test_shutdown_endpoint_flips_should_exit():
    class FakeServer:
        def __init__(self):
            self.should_exit = False

    server = FakeServer()
    set_server(server)
    app = FastAPI()
    attach(app)
    with TestClient(app) as client:
        resp = client.post("/api/shutdown")
    assert resp.status_code == 200
    assert resp.json() == {"status": "shutting down"}
    assert server.should_exit is True


def test_health_endpoint_returns_ok():
    app = FastAPI()
    attach(app)
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_restart_endpoint_returns_restarting():
    """Restart endpoint should return immediately; the actual signal is sent
    on a 0.5s timer, which we don't wait for in this test."""
    app = FastAPI()
    attach(app)
    with TestClient(app) as client:
        resp = client.post("/api/restart")
    assert resp.status_code == 200
    assert resp.json() == {"status": "restarting"}


def test_user_routes_registered_before_attach_take_precedence():
    """FastAPI matches routes in registration order. If user registers
    /api/health first, attach()'s same-path route is shadowed (first wins)."""
    app = FastAPI()

    @app.get("/api/health")
    async def custom_health():
        return {"status": "custom"}

    attach(app)
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "custom"}


def test_attach_weakset_forgets_gcd_apps():
    """WeakSet tracking: after an app is GC'd, attach() on a fresh app must
    register endpoints (regression test for the id()-reuse bug)."""
    import gc

    app1 = FastAPI()
    attach(app1)
    app1_id = id(app1)
    del app1
    gc.collect()

    # Create a new app — even if CPython reuses the memory address, attach()
    # must not skip registration because WeakSet tracks object identity, not id.
    app2 = FastAPI()
    attach(app2)
    paths = {r.path for r in app2.routes if hasattr(r, "path")}
    assert "/api/shutdown" in paths, "attach() must register endpoints on fresh app after GC"
