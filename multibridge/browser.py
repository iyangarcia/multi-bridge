"""The API inside the visitor's browser, for the GitHub Pages demo (Pyodide).

The page's web worker (web/js/navegador.js) unpacks the package and the synthetic examples into
Pyodide's file system and calls `call()` instead of fetching /api/... from a server. The answers are the
ones `multibridge serve` gives (both go through api.route); only these differ:
- rules only: there is no Ollama in a browser (the AI needs the local install);
- recipes and saved field lists live in the browser (IndexedDB, synced by the worker), and the
  visitor's files never leave their computer: nothing here opens a connection.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .api import ApiError, App, route

# calls that write recipes/ or expected/: the worker copies the file system to IndexedDB after them
WRITES = {"/api/approve", "/api/destination/fields", "/api/destination/delete"}


class BrowserApp(App):
    def health(self) -> dict:
        return {"version": __version__, "browser": True, "ollama": {m: False for m in ("qwen3:8b", "qwen3:30b")}}

    def do_propose(self, body: dict) -> dict:
        if (body.get("model") or "rules") not in ("rules", "auto"):
            raise ApiError(503, "la IA necesita la instalación local: aquí solo hay reglas")
        return super().do_propose({**body, "model": "rules"})


_app: BrowserApp | None = None


def start(root: str) -> None:
    global _app
    _app = BrowserApp(Path(root))


def call(method: str, url: str, body: str | None = None) -> str:
    """One API call -> JSON text {"status", "data" | "error", "saved"} (never raises: the worker
    only passes text across)."""
    try:
        data = route(_app, method, url, json.loads(body) if body else None)
        out = {"status": 200, "data": data}
    except ApiError as e:
        out = {"status": e.status, "error": str(e)}
    except json.JSONDecodeError:
        out = {"status": 400, "error": "JSON no válido"}
    except Exception as e:  # same as the server: no traceback with data in it
        out = {"status": 500, "error": f"error interno: {type(e).__name__}"}
    out["saved"] = method == "POST" and url.split("?")[0] in WRITES and out["status"] == 200
    return json.dumps(out, ensure_ascii=False)
