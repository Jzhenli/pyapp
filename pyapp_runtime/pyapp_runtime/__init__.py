"""PyApp runtime: lifecycle endpoints + server abstractions.

This package is intended to be installed into `app_packages/` of a packaged
PyApp application. It provides:

- `create_server(app, ...)`: one-liner for simple projects — creates a uvicorn
  server with `/api/shutdown`, `/api/health`, `/api/restart` auto-registered.
- `attach(app)`: register just the lifecycle endpoints on an existing app
  (for projects that build their own server).
- `set_server(server)`: register a custom server instance so `/api/shutdown`
  can flip its `should_exit`.
- `PyAppServer`: base class for custom server adapters, providing a
  thread-safe `should_exit` backed by `threading.Event`.

`attach` is idempotent; `set_server`/`get_server` are thread-safe. See each
function's docstring for details.
"""

from .lifecycle import attach, get_server, set_server
from .server import PyAppServer, create_server

__all__ = ["attach", "set_server", "get_server", "create_server", "PyAppServer"]
__version__ = "0.1.0"
