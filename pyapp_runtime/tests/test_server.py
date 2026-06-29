"""Tests for pyapp_runtime.server: create_server() + PyAppServer base class."""

import os
import threading

import pytest
import uvicorn
from fastapi import FastAPI

import pyapp_runtime.lifecycle as lifecycle
from pyapp_runtime import PyAppServer, create_server, get_server


@pytest.fixture(autouse=True)
def reset_state():
    yield
    lifecycle._server_ref = None
    lifecycle._attached_apps.clear()


def test_create_server_returns_uvicorn_server():
    app = FastAPI()
    server = create_server(app, port=19990)
    assert isinstance(server, uvicorn.Server)


def test_create_server_auto_registers_server():
    app = FastAPI()
    server = create_server(app, port=19990)
    assert get_server() is server


def test_create_server_auto_attaches_endpoints():
    app = FastAPI()
    create_server(app, port=19990)
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/shutdown" in paths
    assert "/api/health" in paths
    assert "/api/restart" in paths


def test_create_server_respects_env_port():
    app = FastAPI()
    os.environ["APP_PORT"] = "29990"
    try:
        server = create_server(app)
        assert server.config.port == 29990
    finally:
        del os.environ["APP_PORT"]


def test_create_server_explicit_port_overrides_env():
    app = FastAPI()
    os.environ["APP_PORT"] = "29990"
    try:
        server = create_server(app, port=18888)
        assert server.config.port == 18888
    finally:
        del os.environ["APP_PORT"]


def test_create_server_default_port_when_no_env():
    app = FastAPI()
    if "APP_PORT" in os.environ:
        del os.environ["APP_PORT"]
    server = create_server(app)
    assert server.config.port == 18080


def test_create_server_idempotent_with_manual_attach():
    """User calls attach() first, then create_server() — must not duplicate."""
    app = FastAPI()
    from pyapp_runtime import attach

    attach(app)
    route_count_after_attach = len({r.path for r in app.routes if hasattr(r, "path")})
    create_server(app, port=19990)
    route_count_after_create = len({r.path for r in app.routes if hasattr(r, "path")})
    assert route_count_after_attach == route_count_after_create


def test_pyapp_server_should_exit_defaults_false():
    server = PyAppServer()
    assert server.should_exit is False


def test_pyapp_server_should_exit_setter_flips_to_true():
    server = PyAppServer()
    server.should_exit = True
    assert server.should_exit is True


def test_pyapp_server_should_exit_only_true_sets_event():
    """Setting False should not reset the event once set (idempotent stop signal)."""
    server = PyAppServer()
    server.should_exit = True
    server.should_exit = False  # ignored
    assert server.should_exit is True


def test_pyapp_server_run_raises_not_implemented():
    server = PyAppServer()
    with pytest.raises(NotImplementedError):
        server.run()


def test_pyapp_server_constructor_args_stored():
    server = PyAppServer(host="127.0.0.1", port=12345, access_log=True)
    assert server.host == "127.0.0.1"
    assert server.port == 12345
    assert server.access_log is True


def test_pyapp_server_stop_event_is_waitable_across_threads():
    """The internal _stop_event must be usable from another thread via wait()."""
    server = PyAppServer()

    wait_result = []

    def _waiter():
        # Will block until should_exit is set, then return True
        wait_result.append(server._stop_event.wait(timeout=2.0))

    t = threading.Thread(target=_waiter)
    t.start()

    # Give the waiter a moment to start blocking
    t.join(timeout=0.2)
    assert t.is_alive(), "Waiter thread should be blocked"

    server.should_exit = True
    t.join(timeout=1.0)

    assert not t.is_alive(), "Waiter thread should have unblocked"
    assert wait_result == [True], "wait() should return True when event is set"


def test_pyapp_server_with_set_server_enables_shutdown_endpoint():
    """End-to-end: PyAppServer + set_server() should let /api/shutdown flip should_exit."""
    from fastapi.testclient import TestClient

    from pyapp_runtime import attach, set_server

    app = FastAPI()
    attach(app)
    server = PyAppServer()
    set_server(server)

    with TestClient(app) as client:
        resp = client.post("/api/shutdown")

    assert resp.status_code == 200
    assert server.should_exit is True


def test_create_server_accepts_log_level_override():
    """Regression for Issue #4: passing log_level via **uvicorn_kwargs must not
    raise 'multiple values for keyword argument' TypeError."""
    app = FastAPI()
    server = create_server(app, port=19990, log_level="debug")
    assert server.config.log_level == "debug"


def test_create_server_accepts_other_uvicorn_kwargs():
    """**uvicorn_kwargs should be forwarded to uvicorn.Config without conflict."""
    app = FastAPI()
    server = create_server(app, port=19990, timeout_keep_alive=30)
    assert server.config.timeout_keep_alive == 30


def test_pyapp_server_port_falls_back_to_env():
    """Regression for Issue #5: PyAppServer with port=None should read APP_PORT
    env var, mirroring create_server()'s behavior."""
    os.environ["APP_PORT"] = "29990"
    try:
        server = PyAppServer()
        assert server.port == 29990
    finally:
        del os.environ["APP_PORT"]


def test_pyapp_server_default_port_when_no_env():
    """PyAppServer with no env and no explicit port should default to 18080."""
    if "APP_PORT" in os.environ:
        del os.environ["APP_PORT"]
    server = PyAppServer()
    assert server.port == 18080


def test_pyapp_server_explicit_port_overrides_env():
    """Explicit port argument should take precedence over APP_PORT env var."""
    os.environ["APP_PORT"] = "29990"
    try:
        server = PyAppServer(port=12345)
        assert server.port == 12345
    finally:
        del os.environ["APP_PORT"]
