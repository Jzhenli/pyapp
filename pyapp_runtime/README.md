# pyapp-runtime

Runtime lifecycle utilities for [PyApp](https://github.com/Jzhenli/pyapp)-packaged applications.

Provides a unified shutdown/health/restart endpoint layer that works across all PyApp target platforms (Windows, Linux, Android) regardless of the server implementation (uvicorn.Server, custom adapter, etc.).

## Quick Start

### Simple projects

```python
from fastapi import FastAPI
from pyapp_runtime import attach, create_server

app = FastAPI()
attach(app)  # registers /api/shutdown, /api/health, /api/restart

@app.get("/")
async def index():
    return {"hello": "world"}

# create_server() returns a uvicorn.Server with lifecycle endpoints
# already attached. Just call .run() to start.
create_server(app).run()
```

### Complex projects (custom server)

```python
from pyapp_runtime import PyAppServer, attach, set_server

class MyServer(PyAppServer):
    def run(self):
        # Your custom async main loop here.
        # should_exit becomes True when /api/shutdown is hit.
        import asyncio
        asyncio.run(self._async_main())

    async def _async_main(self):
        while not self.should_exit:
            await do_work()

attach(app)            # register endpoints on your FastAPI app
server = MyServer()
set_server(server)     # so /api/shutdown can flip server.should_exit
server.run()
```

## API Reference

### `attach(app: FastAPI) -> FastAPI`

Registers three lifecycle endpoints on the given FastAPI app:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/shutdown` | Sets `server.should_exit = True`, triggering graceful shutdown. |
| GET | `/api/health` | Returns `{"status": "ok"}`. |
| POST | `/api/restart` | Sends SIGTERM (or SIGINT on Windows) to the current process after 0.5s, enabling systemd `Restart=on-failure` to reboot the service. |

Idempotent — safe to call multiple times on the same app instance. Tracking uses a `WeakSet` so destroyed apps are forgotten automatically.

### `create_server(app, host="0.0.0.0", port=None, access_log=True, **uvicorn_kwargs) -> uvicorn.Server`

Creates a `uvicorn.Server` with lifecycle endpoints auto-registered. Calls `attach(app)` and `set_server(server)` internally.

- `port` defaults to `APP_PORT` env var, then `18080`.
- `**uvicorn_kwargs` are forwarded to `uvicorn.Config`.

### `set_server(server) / get_server()`

Thread-safe module-level server reference. `create_server()` calls `set_server()` automatically; custom servers must call it explicitly after construction.

### `PyAppServer`

Base class for custom server adapters. Provides a `should_exit` property backed by `threading.Event`, safe to set from any thread. Subclass and override `run()`.

## How It Works

All shutdown paths converge to flipping `should_exit` on the registered server:

```
HTTP POST /api/shutdown  ──┐
                           ├──> server.should_exit = True  ──> graceful exit
Android JNI stop_server ───┘
```

The server reference is duck-typed — any object with a writable `should_exit` attribute works (uvicorn.Server, PyAppServer subclass, custom adapter).

## License

MIT
