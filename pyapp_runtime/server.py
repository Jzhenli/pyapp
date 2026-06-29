"""Server creation helpers and base class for custom servers."""

import os
import threading

import uvicorn
from fastapi import FastAPI

from .lifecycle import attach, set_server


def create_server(
    app: FastAPI,
    host: str = "0.0.0.0",
    port: int | None = None,
    access_log: bool = True,
    **uvicorn_kwargs,
):
    """Create a uvicorn server with lifecycle endpoints auto-registered.

    For simple projects, this is the only API needed::

        from pyapp_runtime import create_server
        create_server(app).run()

    The returned object is a vanilla `uvicorn.Server` — existing code that
    inspects `server.should_exit` or `server.run()` keeps working.

    Args:
        app: FastAPI application instance.
        host: Bind host. Defaults to "0.0.0.0".
        port: Bind port. Falls back to `APP_PORT` env var, then 18080.
        access_log: Enable uvicorn access log. Defaults to True.
        **uvicorn_kwargs: Extra kwargs forwarded to `uvicorn.Config`.

    Returns:
        uvicorn.Server instance (not yet started).
    """
    if port is None:
        port = int(os.environ.get("APP_PORT", "18080"))

    attach(app)  # idempotent — safe if user already called attach() manually

    # Allow callers to override log_level (and any other uvicorn.Config kwarg)
    # via **uvicorn_kwargs without triggering "multiple values for keyword
    # argument" TypeError.
    uvicorn_kwargs.setdefault("log_level", "info")
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        access_log=access_log,
        **uvicorn_kwargs,
    )
    server = uvicorn.Server(config)
    set_server(server)
    return server


class PyAppServer:
    """Base class for custom server adapters (complex projects).

    Subclass and override `run()`. The `should_exit` property is wired to an
    internal `threading.Event`, so it is safe to set from any thread (e.g. the
    FastAPI request thread handling `/api/shutdown`) and waitable from another
    thread or async context.

    Example::

        class MyServer(PyAppServer):
            def run(self):
                asyncio.run(self._async_main())

            async def _async_main(self):
                await async_main(stop_event=self._stop_event)

    Contract:
        - `should_exit` (read/write bool): setting True signals the server to
          stop. Compatible with uvicorn.Server's attribute of the same name.
        - `run()`: blocking entry point. Must return when should_exit is set.
    """

    def __init__(self, host: str = "0.0.0.0", port: int | None = None, access_log: bool = False):
        self.host = host
        # Mirror create_server()'s APP_PORT fallback so subclasses get a
        # concrete port by default, consistent with the simple-project path.
        if port is None:
            port = int(os.environ.get("APP_PORT", "18080"))
        self.port = port
        self.access_log = access_log
        self._stop_event = threading.Event()

    @property
    def should_exit(self) -> bool:
        return self._stop_event.is_set()

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        if value:
            self._stop_event.set()

    def run(self):
        raise NotImplementedError("Subclass must implement run()")
