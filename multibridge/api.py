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
    GET  /api/formats                     formats a destination can be (and which need no example)
    POST /api/fields   {upload_id}        → every field of that source, typed: a starting field list
    POST /api/destination/fields {format, fields, name?, upload_id?, delimiter?, replace?, save?}
                                          → a destination with no example; a field's "from" ties it to a column;
                                            "save" writes expected/<name>.fields.json (names and types only)
    GET  /api/destination/fields?destination=ID   a field-list destination's fields, to edit them
    POST /api/destination/delete {key}    remove a saved field list or a destination in memory
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
from .expected import FIELDS_SUFFIX, Expected, destination_name, fields_from_rows, save_fields
from .formats import FORMATS
from .parsers import parse_bytes
from .proposer import propose
from .records import Rows, to_rows

HOST = "127.0.0.1"
MAX_BODY = 25 * 1024 * 1024
MAX_UPLOADS = 10
EXAMPLE_SUFFIXES = {ext for f in FORMATS.values() for ext in f.extensions}
NOT_EXAMPLES = {"answers.json", "destino_expected.json"}
CLIENT_GONE = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


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
        self.ties: OrderedDict[str, dict] = OrderedDict()   # destination key -> {target: source column}, memory only
        self.lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------------------------
    def _folder(self) -> dict[str, Path]:
        """Examples first (the first one is the default destination), then saved field lists."""
        found = sorted(self.expected_dir.glob("*.example.*")) + sorted(self.expected_dir.glob("*" + FIELDS_SUFFIX))
        return {destination_name(p.name): p for p in found}

    def _saved(self, key: str | None) -> Path | None:
        """The saved field list behind a destination key, if that is what it is."""
        p = self._folder().get(key or "")
        return p if p is not None and p.name.endswith(FIELDS_SUFFIX) else None

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
        for folder in (self.root / "examples", self.root / "examples" / "hard", self.root / "examples" / "pedidos"):
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
                saved = path.name.endswith(FIELDS_SUFFIX)
                out.append({"key": key, "name": e.name, "file": path.name, "format": e.format,
                            "label": formats.get(e.format).label, "fields": len(e.targets),
                            "origin": "guardado" if saved else origin, "editable": saved})
        with self.lock:
            for key, d in self.destinations.items():
                e = d["expected"]
                out.append({"key": key, "name": e.name, "file": d["file"], "format": e.format,
                            "label": formats.get(e.format).label, "fields": len(e.targets),
                            "origin": "medida" if key.startswith("medida-") else "subido", "editable": "fields" in d})
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

    @staticmethod
    def list_formats() -> list[dict]:
        """Formats a destination can be: `blank` ones need no example, only a list of fields."""
        return [{"name": f.name, "label": f.label, "extension": f.extension, "blank": f.can_blank}
                for f in FORMATS.values()]

    def source_fields(self, body: dict) -> dict:
        """Every field of an uploaded source, typed: the starting list for a destination with no example."""
        return {"fields": fields_from_rows(self._upload(body.get("upload_id", ""))["rows"])}

    def fields_destination(self, body: dict) -> dict:
        """A destination from a format and a field list (no example). A field's "from" names the source
        column it comes from: the proposal then takes it as decided (the person chose it), not guessed.

        Memory only by default, like uploaded examples. With "save", it is written to
        expected/<name>.fields.json: field names and types only, never values (C13)."""
        fmt = str(body.get("format") or "")
        if fmt not in FORMATS:
            raise ApiError(400, "formato desconocido")
        fields = body.get("fields")
        if not isinstance(fields, list):
            raise ApiError(400, "faltan los campos")
        save = bool(body.get("save"))
        typed = str(body.get("name") or "").strip()
        name = "".join(ch for ch in typed if ch.isalnum() or ch in "-_")[:40]
        if save and (not name or name != typed):
            raise ApiError(400, "el nombre del formato solo puede tener letras, números, - y _ (hasta 40)")
        name = name or f"a-medida-{fmt}"
        options = {"delimiter": body["delimiter"]} if body.get("delimiter") else {}
        try:
            e = Expected.from_fields(fmt, fields, name, options)
        except formats.UnsupportedFormat as ex:
            raise ApiError(422, str(ex)) from None
        except ValueError as ex:
            raise ApiError(400, str(ex)) from None
        columns = self._upload(body["upload_id"])["rows"].columns if body.get("upload_id") else {}
        direct = {t.path: f["from"] for f, t in zip(fields, e.targets)
                  if isinstance(f.get("from"), str) and f["from"] in columns}
        replace = str(body.get("replace") or "")
        listed = [{"name": t.leaf, "type": t.type, "required": t.required, "multiple": t.multiple} for t in e.targets]
        if save:
            key = name
            taken = self._folder().get(name)
            if taken is not None and (not taken.name.endswith(FIELDS_SUFFIX) or name != replace):
                raise ApiError(409, f"ya hay un destino llamado {name}: elige otro nombre")
            self.expected_dir.mkdir(exist_ok=True)
            save_fields(self.expected_dir / f"{name}{FIELDS_SUFFIX}", fmt, listed)
            old = self._saved(replace)
            if old is not None and replace != name:   # renamed: the old file goes
                old.unlink()
        else:
            with self.lock:   # editing the list again replaces the same destination instead of piling up new ones
                key = replace if replace.startswith("medida-") and replace in self.destinations \
                    else "medida-" + secrets.token_urlsafe(8)
                self.destinations[key] = {"file": f"a medida ({formats.get(fmt).label})", "expected": e,
                                          "fields": listed}
                while len(self.destinations) > MAX_UPLOADS:
                    self.destinations.popitem(last=False)
        with self.lock:
            self.ties[key] = direct
            while len(self.ties) > MAX_UPLOADS:
                self.ties.popitem(last=False)
        return {**self.get_expected(key), "fields": [{**f, "from": direct.get(t.path)} for f, t in zip(listed, e.targets)]}

    def destination_fields(self, dest: str | None) -> dict:
        """The field list of a destination made from one (to edit it). Destinations made from an example
        have none: they change by changing the example."""
        e = self.expected(dest)
        saved = self._saved(dest)
        with self.lock:
            mem = self.destinations.get(dest or "") or {}
        if saved is None and "fields" not in mem:
            raise ApiError(409, "este destino sale de un ejemplo: para cambiarlo, cambia o sube el ejemplo")
        fields = mem.get("fields") or json.loads(saved.read_text(encoding="utf-8"))["fields"]
        return {"key": dest, "name": e.name, "format": e.format, "saved": saved is not None,
                "fields": [{k: f.get(k, False if k == "required" else None) for k in ("name", "type", "required", "multiple")}
                           for f in fields]}

    def delete_destination(self, body: dict) -> dict:
        """Remove a saved field list or a destination kept in memory. Examples in the folder are files
        the user manages; they are never deleted from here."""
        key = str(body.get("key") or "")
        saved = self._saved(key)
        with self.lock:
            in_memory = self.destinations.pop(key, None)
            self.ties.pop(key, None)
        if saved is not None:
            saved.unlink()
        elif in_memory is None:
            raise ApiError(404 if key not in self._folder() and key not in self._example_destinations() else 409,
                           "solo se pueden quitar formatos hechos con una lista de campos o subidos")
        return {"deleted": key}

    def _direct(self, dest: str | None) -> dict[str, str]:
        with self.lock:
            return dict(self.ties.get(dest or "") or {})

    @staticmethod
    def _direct_draft(draft: dict, rows: Rows, expected: Expected, direct: dict[str, str]) -> dict:
        """The proposal with every field the person tied to a column when building the destination.
        Only the transforms are worked out (type and format); the rest keeps the rules proposal."""
        pack = packs.get(expected.pack)
        taken = {c for c in direct.values() if c in rows.columns}
        fields = {}
        for t in expected.targets:
            col = direct.get(t.path)
            if col in rows.columns:
                transforms, issues, pending = matcher.transforms_for(rows, [col], t, pack)
                fields[t.path] = {"status": "pending" if pending else "mapped", "from": [col], "transforms": transforms,
                                  "confidence": 0.99, "why": ["elegido al crear el destino"], "issues": issues,
                                  "proposed_by": "direct"}
            else:
                f = {k: v for k, v in draft["fields"][t.path].items() if k != "proposal"}
                if set(f["from"]) & taken:
                    f.update(status="no_data", **{"from": []}, transforms=[], confidence=None)
                fields[t.path] = f
        out = recipes.new(draft["recipe"], rows, expected, fields, proposed_by="rules")
        out["proposer"] = {"model": "direct"}
        return out

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
        direct = self._direct(body.get("destination"))
        if direct and all(t.path in direct for t in expected.targets):
            model = "rules"   # nothing left to guess: no model needed
        try:
            draft = propose(rows, expected, model=model, name=Path(up["name"]).stem, recipes_dir=self.recipes_dir)
        except ollama.OllamaUnavailable as e:
            raise ApiError(503, f"el modelo local no responde: {e}") from None
        if direct:
            draft = self._direct_draft(draft, rows, expected, direct)
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
        try:
            if not self._host_ok():
                return self._send(403, {"error": "solo se admiten peticiones desde este equipo"})
            try:
                return fn()
            except ApiError as e:
                return self._send(e.status, {"error": str(e)})
            except CLIENT_GONE:
                raise
            except Exception as e:  # never leak a traceback with data in it
                return self._send(500, {"error": f"error interno: {type(e).__name__}"})
        except CLIENT_GONE:   # the browser dropped the request (reload, another page): nobody to answer
            self.close_connection = True

    def do_GET(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _get(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        routes = {"/api/health": self.app.health, "/api/destinations": self.app.list_destinations,
                  "/api/formats": self.app.list_formats,
                  "/api/examples": self.app.list_examples, "/api/recipes": self.app.list_recipes}
        if path == "/api/expected":
            return self._send(200, self.app.get_expected((query.get("destination") or [None])[0]))
        if path == "/api/destination/fields":
            return self._send(200, self.app.destination_fields((query.get("destination") or [None])[0]))
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
                  "/api/destination": self.app.upload_destination, "/api/fields": self.app.source_fields,
                  "/api/destination/fields": self.app.fields_destination,
                  "/api/destination/delete": self.app.delete_destination}
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
