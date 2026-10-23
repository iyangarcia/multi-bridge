"""Local HTTP API + the review web app (web/). Standard library only.

    multibridge serve                 # http://127.0.0.1:8766

Security (docs/COMPLIANCE.md):
- Listens on 127.0.0.1 only and rejects requests whose Host header isn't this machine
  (protects against DNS rebinding: a web page elsewhere can't drive the API through the browser).
- Uploaded files (sources and destination examples) live in memory only, for the session;
  nothing is written to out/ (C13).
  Approved recipes are saved to recipes/ (structure only, no personal data, C12).
- Static files are served only from web/, never outside it.

Endpoints (JSON):
    GET  /api/health                      version, Ollama status
    GET  /api/destinations                destinations: expected/*.example.* (+ rules) and uploaded ones
    GET  /api/expected?destination=ID     one destination's fields (default: the first in expected/)
    POST /api/destination {name, content_b64, rules?}    → an uploaded example of the output, any format
    GET  /api/examples                    synthetic example files that can be loaded
    GET  /api/recipes                     approved recipes (summary)
    GET  /api/recipes/<name>              one approved recipe (download)
    POST /api/upload   {name, content_b64} | {example}   → upload_id, columns, notes, AI view, samples
    POST /api/propose  {upload_id, model, destination}   → draft recipe, reusable recipe, ranking, previews
    POST /api/field    {upload_id, target, from, destination}  → transforms, issues, status, preview
    POST /api/approve  {upload_id, draft, by, carry, destination} → approved recipe (saved) + output
    POST /api/run      {upload_id, recipe, destination}  → output with an approved recipe
The output comes as nested records (preview) and as a file in the destination's own format,
checked by its plug-in.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import secrets
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, matcher, recipe as recipes
from .ai import ollama
from .aiview import source_view
from .engine import TransformError, field_value, run
from . import formats, packs
from .expected import Expected, destination_name
from .formats import FORMATS
from .parsers import parse_bytes
from .proposer import propose
from .records import Rows, to_rows

HOST = "127.0.0.1"
MAX_BODY = 25 * 1024 * 1024
MAX_UPLOADS = 10
EXAMPLE_SUFFIXES = {ext for f in FORMATS.values() for ext in f.extensions}
NOT_EXAMPLES = {"answers.json", "destino_expected.json"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    """State and logic, independent of HTTP (easy to test)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.web = self.root / "web"
        self.recipes_dir = self.root / "recipes"
        self.expected_dir = self.root / "expected"
        self.uploads: OrderedDict[str, dict] = OrderedDict()
        self.destinations: OrderedDict[str, dict] = OrderedDict()   # uploaded examples, memory only
        self.lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------------------------
    def _folder(self) -> dict[str, Path]:
        return {destination_name(p.name): p for p in sorted(self.expected_dir.glob("*.example.*"))}

    def _example_destinations(self) -> dict[str, Path]:
        """Synthetic example destinations (examples/destinos/), to try other formats."""
        folder = self.root / "examples" / "destinos"
        return {"ejemplo-" + destination_name(p.name): p for p in sorted(folder.glob("*.example.*"))}

    def expected(self, dest: str | None = None) -> Expected:
        """A destination by id: an uploaded one, one in expected/, or (no id) the first in expected/."""
        if dest:
            with self.lock:
                up = self.destinations.get(dest)
            if up is not None:
                return up["expected"]
        folder = self._folder()
        path = (folder.get(dest) or self._example_destinations().get(dest)) if dest else next(iter(folder.values()), None)
        if path is None:
            raise ApiError(404, "destino no encontrado" if dest else "no hay ningún destino en expected/")
        try:
            return Expected.load(path)
        except (ValueError, KeyError) as e:
            raise ApiError(422, f"no se pudo leer el destino {path.name}: {e}") from None


    def _upload(self, upload_id: str) -> dict:
        with self.lock:
            up = self.uploads.get(upload_id)
        if up is None:
            raise ApiError(404, "archivo no encontrado: vuelve a subirlo")
        return up

    def _examples(self) -> dict[str, Path]:
        out = {}
        for folder in (self.root / "examples", self.root / "examples" / "hard"):
            for p in sorted(folder.glob("*")):
                if p.suffix.lower() in EXAMPLE_SUFFIXES and p.name not in NOT_EXAMPLES:
                    out[p.relative_to(self.root / "examples").as_posix()] = p
        return out

    @staticmethod
    def _columns(rows: Rows) -> list[dict]:
        return [{"column": c, "label": f.label, "description": f.description, "entity": f.entity,
                 "dtype": f.dtype, "format": f.format, "unit": f.unit, "kind": f.kind, "custom": f.custom,
                 "sensitive": f.sensitive, "null_ratio": f.null_ratio}
                for c, f in rows.columns.items() if f.dtype != "empty"]

    @staticmethod
    def _samples(rows: Rows, n: int = 3) -> dict[str, list]:
        """Real values, for the reviewer on this machine only ("Tus datos"). Never sent to any model."""
        out = {}
        for c in rows.columns:
            vals = []
            for v in rows.values(c):
                for x in v if isinstance(v, list) else [v]:
                    if x not in (None, "") and x not in vals:
                        vals.append(x)
                if len(vals) >= n:
                    break
            out[c] = vals[:n]
        return out

    @staticmethod
    def _preview(rows: Rows, spec: dict, target) -> dict | None:
        """First row's value before and after the transforms, computed by the real engine."""
        if not spec.get("from"):
            return None
        for row in rows.rows:
            before = [row.get(c) for c in spec["from"]]
            if all(b in (None, "", []) for b in before):
                continue
            try:
                after, error = field_value(row, spec, target), None
            except TransformError as e:
                after, error = None, str(e)
            problem = error or Expected.check(target, after)
            return {"before": before[0] if len(before) == 1 else before, "after": after, "problem": problem}
        return {"before": None, "after": None, "problem": "ninguna fila tiene datos en esa columna"}

    # -- endpoints -------------------------------------------------------------------------------
    def health(self) -> dict:
        return {"version": __version__, "ollama": {m: ollama.available(m) for m in ("qwen3:8b", "qwen3:30b")}}

    def get_expected(self, dest: str | None = None) -> dict:
        e = self.expected(dest)
        return {"id": e.id, "key": dest or next(iter(self._folder()), e.name), "name": e.name, "format": e.format,
                "label": formats.get(e.format).label, "pack": e.pack, "group_by": e.group_by, "groups": e.groups,
                "constants": len(e.constants), "targets": [
                    {"path": t.path, "type": t.type, "concept": t.concept, "required": t.required, "enum": t.enum,
                     "unit": t.unit, "description": t.description, "example": t.example, "group": t.group,
                     "leaf": t.leaf}
                    for t in e.targets]}

    def list_destinations(self) -> list[dict]:
        out = []
        for origin, found in (("carpeta", self._folder()), ("ejemplo", self._example_destinations())):
            for key, path in found.items():
                try:
                    e = Expected.load(path)
                except (ValueError, KeyError):
                    continue
                out.append({"key": key, "name": e.name, "file": path.name, "format": e.format,
                            "label": formats.get(e.format).label, "fields": len(e.targets), "origin": origin})
        with self.lock:
            for key, d in self.destinations.items():
                e = d["expected"]
                out.append({"key": key, "name": e.name, "file": d["file"], "format": e.format,
                            "label": formats.get(e.format).label, "fields": len(e.targets), "origin": "subido"})
        return out

    def upload_destination(self, body: dict) -> dict:
        """An example of the output in any format. Kept in memory only: an example can hold a real record."""
        name = Path(str(body.get("name") or "destino")).name
        try:
            data = base64.b64decode(body.get("content_b64") or "", validate=True)
        except (binascii.Error, ValueError):
            raise ApiError(400, "contenido no válido") from None
        rules = body.get("rules")
        if rules is not None and not isinstance(rules, dict):
            raise ApiError(400, "las reglas deben ser un objeto JSON")
        try:
            e = Expected.from_bytes(data, name, rules=rules)
        except Exception as ex:  # any reader failure goes back to the user, not a stack trace
            raise ApiError(422, f"no se pudo usar {name} como destino: {ex}") from None
        if not e.targets:
            raise ApiError(422, f"{name}: el ejemplo no tiene campos")
        key = "subido-" + secrets.token_urlsafe(8)
        with self.lock:
            self.destinations[key] = {"file": name, "expected": e}
            while len(self.destinations) > MAX_UPLOADS:
                self.destinations.popitem(last=False)
        return self.get_expected(key)

    def list_examples(self) -> list[dict]:
        return [{"name": name, "size": p.stat().st_size} for name, p in self._examples().items()]

    def list_recipes(self) -> list[dict]:
        out = []
        for p in sorted(self.recipes_dir.glob("*.json")) if self.recipes_dir.is_dir() else []:
            try:
                r = recipes.load(p)
                recipes.verify(r)
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            fields = r["fields"].values()
            out.append({"name": r["recipe"], "file": r["source"]["file"], "format": r["source"]["format"],
                        "expected": r["expected"], "approved_by": r["approval"]["by"], "at": r["approval"]["at"],
                        "mapped": sum(f["status"] == "mapped" for f in fields), "total": len(r["fields"])})
        return out

    def get_recipe(self, name: str) -> dict:
        p = (self.recipes_dir / f"{name}.json").resolve()
        if p.parent != self.recipes_dir.resolve() or not p.is_file():
            raise ApiError(404, "receta no encontrada")
        return recipes.load(p)

    def upload(self, body: dict) -> dict:
        if body.get("example"):
            path = self._examples().get(body["example"])
            if path is None:
                raise ApiError(404, "ejemplo no encontrado")
            name, data = path.name, path.read_bytes()
        else:
            name = Path(str(body.get("name") or "archivo")).name
            try:
                data = base64.b64decode(body.get("content_b64") or "", validate=True)
            except (binascii.Error, ValueError):
                raise ApiError(400, "contenido no válido") from None
            if not data:
                raise ApiError(400, "archivo vacío")
        try:
            rows = to_rows(parse_bytes(data, name))
        except Exception as e:  # any parser failure goes back to the user, not a stack trace
            raise ApiError(422, f"no se pudo leer {name}: {e}") from None
        upload_id = secrets.token_urlsafe(12)
        with self.lock:
            self.uploads[upload_id] = {"name": name, "rows": rows}
            while len(self.uploads) > MAX_UPLOADS:
                self.uploads.popitem(last=False)   # memory only, oldest out (COMPLIANCE C13)
        return {"upload_id": upload_id, "name": name, "format": rows.format, "rows": len(rows.rows),
                "notes": rows.notes, "columns": self._columns(rows), "ai_view": source_view(rows),
                "samples": self._samples(rows)}

    def do_propose(self, body: dict) -> dict:
        up = self._upload(body.get("upload_id", ""))
        rows, expected = up["rows"], self.expected(body.get("destination"))
        found = recipes.find(self.recipes_dir, rows, expected)
        reusable = None
        if found:
            path, r = found[0]
            reusable = {"name": r["recipe"], "approved_by": r["approval"]["by"], "at": r["approval"]["at"]}
        model = body.get("model") or "rules"
        if model not in ("rules", "auto", "qwen3:8b", "qwen3:30b"):
            raise ApiError(400, "modelo no permitido")
        try:
            draft = propose(rows, expected, model=model, name=Path(up["name"]).stem, recipes_dir=self.recipes_dir)
        except ollama.OllamaUnavailable as e:
            raise ApiError(503, f"el modelo local no responde: {e}") from None
        previews = {t.path: self._preview(rows, draft["fields"][t.path], t) for t in expected.targets}
        with self.lock:
            up["draft"] = json.loads(json.dumps(draft))   # the server's own copy: provenance can't be edited
            up["destination"] = expected.id
        return {"draft": draft, "reusable": reusable, "ranking": matcher.ranking(rows, expected), "previews": previews}

    def field(self, body: dict) -> dict:
        up = self._upload(body.get("upload_id", ""))
        rows, expected = up["rows"], self.expected(body.get("destination"))
        try:
            t = expected.get(body.get("target", ""))
        except KeyError:
            raise ApiError(400, "campo de destino desconocido") from None
        cols = [c for c in body.get("from") or [] if isinstance(c, str)]
        unknown = [c for c in cols if c not in rows.columns]
        if unknown:
            raise ApiError(400, f"columnas desconocidas: {', '.join(unknown)}")
        if not cols:
            return {"status": "no_data", "from": [], "transforms": [], "issues": [], "preview": None}
        transforms, issues, pending = matcher.transforms_for(rows, cols, t, packs.get(expected.pack))
        spec = {"status": "pending" if pending else "mapped", "from": cols, "transforms": transforms}
        return {**spec, "issues": issues, "preview": self._preview(rows, spec, t)}

    def approve(self, body: dict) -> dict:
        """The browser sends only the reviewer's *decisions*. Everything else (what was proposed, by whom,
        the structure signature used for reuse) is rebuilt here from the server's own copy."""
        up = self._upload(body.get("upload_id", ""))
        proposal = up.get("draft")
        if proposal is None:
            raise ApiError(409, "primero hay que pedir una propuesta")
        decisions = (body.get("draft") or {}).get("fields")
        if not isinstance(decisions, dict):
            raise ApiError(400, "faltan las decisiones")
        rows, expected = up["rows"], self.expected(body.get("destination"))
        if up.get("destination") != expected.id:
            raise ApiError(409, "la propuesta se hizo para otro destino: vuelve a pedirla")
        fields = {}
        for t in expected.targets:
            d, p = decisions.get(t.path) or {}, proposal["fields"][t.path]
            cols = [c for c in d.get("from") or [] if isinstance(c, str)]
            if any(c not in rows.columns for c in cols):
                raise ApiError(400, f"{t.path}: columna desconocida")
            status = d.get("status") if d.get("status") in recipes.STATUSES else "pending"
            transforms = d.get("transforms") if isinstance(d.get("transforms"), list) else []
            fields[t.path] = {"status": status, "from": cols, "transforms": transforms,
                              "confidence": p.get("confidence"), "why": p.get("why", []), "issues": p.get("issues", [])}
        name = "".join(ch for ch in Path(up["name"]).stem if ch.isalnum() or ch in "-_") or "receta"
        folder = self._folder()
        if not folder or expected.name != next(iter(folder)):   # one recipe file per source and destination
            name += "-" + "".join(ch for ch in expected.name if ch.isalnum() or ch in "-_")
        final = recipes.new(name, rows, expected, fields, proposed_by="")
        for t in expected.targets:   # provenance from what was really proposed, not from the browser
            final["fields"][t.path]["proposed_by"] = proposal["fields"][t.path].get("proposed_by")
            final["fields"][t.path]["proposal"] = proposal["fields"][t.path]["proposal"]
        final["proposer"] = proposal.get("proposer")
        try:
            carry = [c for c in body.get("carry") or [] if isinstance(c, str)]
            approved = recipes.approve(final, expected, str(body.get("by") or ""), carry=carry)
        except recipes.ApprovalError as e:
            raise ApiError(409, "; ".join(e.problems)) from None
        recipes.save(approved, self.recipes_dir / f"{name}.json")
        return {"recipe": approved, **self._run(rows, approved, expected)}

    def do_run(self, body: dict) -> dict:
        up = self._upload(body.get("upload_id", ""))
        expected = self.expected(body.get("destination"))
        r = self.get_recipe(str(body.get("recipe") or ""))
        why = recipes.compatible(r, up["rows"], expected)
        if why:
            raise ApiError(409, "la receta no encaja con este archivo: " + "; ".join(why))
        return {"recipe": r, **self._run(up["rows"], r, expected)}

    @staticmethod
    def _run(rows: Rows, r: dict, expected: Expected) -> dict:
        try:
            result = run(rows, r, expected)
        except recipes.ApprovalError as e:
            raise ApiError(409, str(e)) from None
        fmt = formats.get(expected.format)
        data = result.write(expected)
        stem = Path(rows.source).stem
        return {"records": result.records, "report": result.report,
                "output": {"filename": f"{stem}_{expected.name}{fmt.extension}", "format": fmt.name,
                           "label": fmt.label, "mime": fmt.mime, "problems": fmt.check(data),
                           "content_b64": base64.b64encode(data).decode("ascii")}}


class Handler(BaseHTTPRequestHandler):
    app: App   # set by make_server
    server_version = "MultiBridge"

    def log_message(self, fmt, *args):   # no request logs: URLs and bodies can carry file names
        pass

    def _send(self, status: int, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    def _guard(self, fn):
        if not self._host_ok():
            return self._send(403, {"error": "solo se admiten peticiones desde este equipo"})
        try:
            return fn()
        except ApiError as e:
            return self._send(e.status, {"error": str(e)})
        except Exception as e:  # never leak a traceback with data in it
            return self._send(500, {"error": f"error interno: {type(e).__name__}"})

    def do_GET(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _get(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        routes = {"/api/health": self.app.health, "/api/destinations": self.app.list_destinations,
                  "/api/examples": self.app.list_examples, "/api/recipes": self.app.list_recipes}
        if path == "/api/expected":
            return self._send(200, self.app.get_expected((query.get("destination") or [None])[0]))
        if path in routes:
            return self._send(200, routes[path]())
        if path.startswith("/api/recipes/"):
            return self._send(200, self.app.get_recipe(unquote(path[len("/api/recipes/"):])))
        if path.startswith("/api/"):
            raise ApiError(404, "no existe")
        return self._static(path)

    def _post(self):
        path = urlparse(self.path).path
        routes = {"/api/upload": self.app.upload, "/api/propose": self.app.do_propose, "/api/field": self.app.field,
                  "/api/approve": self.app.approve, "/api/run": self.app.do_run,
                  "/api/destination": self.app.upload_destination}
        if path not in routes:
            raise ApiError(404, "no existe")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "archivo demasiado grande")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ApiError(415, "se espera JSON")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "JSON no válido") from None
        if not isinstance(body, dict):
            raise ApiError(400, "se espera un objeto JSON")
        return self._send(200, routes[path](body))

    def _static(self, path: str):
        rel = unquote(path).lstrip("/") or "index.html"
        web = self.app.web.resolve()
        target = (web / rel).resolve()
        if web not in target.parents and target != web or not target.is_file():
            raise ApiError(404, "no existe")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        return self._send(200, target.read_bytes(), ctype)


def make_server(root: Path, port: int = 8766) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": App(root)})
    return ThreadingHTTPServer((HOST, port), handler)


def serve(root: Path, port: int = 8766) -> None:
    server = make_server(root, port)
    print(f"Multi Bridge en http://{HOST}:{server.server_address[1]}  (solo este equipo; Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
