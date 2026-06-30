"""Lifecycle endpoints manager.

Idempotent registration of `/api/shutdown`, `/api/health`, `/api/restart` on a
FastAPI app, plus a module-level server reference so the shutdown endpoint can
flip `should_exit` regardless of which server implementation is in use
(uvicorn.Server, custom adapter, PyAppServer subclass). `set_server`/`get_server`
are thread-safe; `attach` is idempotent but not synchronized — call it from a
single thread during application startup.
"""

import logging
import os
import signal
import sys
import threading
import weakref

from fastapi import FastAPI
from fastapi.responses import JSONResponse

_logger = logging.getLogger("pyapp_runtime")

_server_ref = None
_server_lock = threading.Lock()
# WeakSet so GC'd apps are automatically removed — avoids id() reuse bugs
# where a new FastAPI instance could be mistaken for an already-attached one.
_attached_apps: weakref.WeakSet = weakref.WeakSet()


def set_server(server):
    """Register the server instance so `/api/shutdown` can flip its should_exit.

    Thread-safe. Called automatically by `create_server()`, but custom servers
    (e.g. XAgentServer) must call this explicitly after construction.
    """
    global _server_ref
    with _server_lock:
        _server_ref = server


def get_server():
    """Return the currently registered server instance (or None)."""
    with _server_lock:
        return _server_ref


def attach(app: FastAPI):
    """Attach lifecycle endpoints to `app`.

    Registers `/api/shutdown`, `/api/health`, `/api/restart` if not already
    attached. Idempotent: safe to call multiple times on the same app instance
    (e.g. across reloads or in tests). Tracking uses a WeakSet so destroyed
    apps are forgotten automatically.

    Returns the app for chaining: `app = attach(FastAPI())`.
    """
    if app in _attached_apps:
        return app
    _attached_apps.add(app)

    @app.post("/api/shutdown")
    async def _shutdown():
        server = get_server()
        if server is None:
            return JSONResponse(
                {"status": "error", "message": "server not initialized"},
                status_code=500,
            )
        # Duck-typed: works with uvicorn.Server, PyAppServer, or any custom
        # adapter that exposes a writable should_exit attribute.
        server.should_exit = True
        return {"status": "shutting down"}

    @app.get("/api/health")
    async def _health():
        return {"status": "ok"}

    @app.post("/api/restart")
    async def _restart():
        # Sending a signal to self so systemd's Restart=on-failure will reboot
        # us (graceful exit with code 0 does not trigger restart).
        def _do_restart():
            sig = signal.SIGINT if sys.platform == "win32" else signal.SIGTERM
            try:
                os.kill(os.getpid(), sig)
            except Exception as e:
                _logger.warning("Failed to send restart signal %s: %s", sig, e)

        threading.Timer(0.5, _do_restart).start()
        return {"status": "restarting"}

    return app
