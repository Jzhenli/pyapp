"""End-to-end integration test: real HTTP request to /api/shutdown triggers
graceful server exit via uvicorn's should_exit mechanism."""

import sys
import threading
import time
import urllib.request

import pytest
from fastapi import FastAPI

import pyapp_runtime.lifecycle as lifecycle
from pyapp_runtime import create_server


@pytest.fixture(autouse=True)
def reset_state():
    yield
    lifecycle._server_ref = None
    lifecycle._attached_apps.clear()


def _wait_for_server_ready(port: int, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def test_shutdown_endpoint_triggers_graceful_uvicorn_exit():
    """Spin up a real uvicorn server in a background thread, POST /api/shutdown,
    and verify the server thread exits within a reasonable window."""
    port = 18999
    app = FastAPI()
    server = create_server(app, host="127.0.0.1", port=port, access_log=False)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    try:
        assert _wait_for_server_ready(port), "Server failed to start in time"
        assert server.should_exit is False

        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", method="POST")
        with urllib.request.urlopen(req, timeout=2) as r:
            assert r.status == 200
            assert b"shutting down" in r.read()

        # uvicorn should observe should_exit and unwind the main loop
        server_thread.join(timeout=5.0)
        assert not server_thread.is_alive(), "Server thread should have exited after /api/shutdown"
        assert server.should_exit is True
    finally:
        # Defensive: if anything went wrong, force the server down so the
        # process can exit cleanly.
        server.should_exit = True
        server_thread.join(timeout=2.0)


def test_pyapp_server_subclass_works_with_attach_and_set_server():
    """Simulate the XAgent pattern: custom server subclass + attach(app) +
    set_server(server), then POST /api/shutdown should flip _stop_event."""

    class FakeCustomServer:
        """Mimics XAgentServer's contract — no inheritance, just duck typing."""

        def __init__(self):
            self._stop_event = threading.Event()

        @property
        def should_exit(self):
            return self._stop_event.is_set()

        @should_exit.setter
        def should_exit(self, value):
            if value:
                self._stop_event.set()

    from pyapp_runtime import attach, set_server

    app = FastAPI()
    attach(app)
    server = FakeCustomServer()
    set_server(server)

    # We can't easily run a real HTTP server backed by FakeCustomServer (it
    # doesn't speak uvicorn). Instead, invoke the endpoint handler directly
    # via FastAPI's TestClient to verify the wiring.
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.post("/api/shutdown")

    assert resp.status_code == 200
    assert resp.json() == {"status": "shutting down"}
    assert server._stop_event.is_set(), "_stop_event should be set so the custom server's run() can unblock"
