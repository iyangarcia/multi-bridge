"""Recipes: the approved "this column goes to that field, transformed like this" (hackathon "receta").

    {
      "recipe": "huca_oviedo_hl7v23", "status": "draft" | "approved",
      "expected": "cdss_paciente#f634a246",
      "source": {"file": ..., "format": "hl7v2", "signature": [["PID-5.2", "string"], ...]},
      "fields": {
        "paciente.nombre": {"status": "mapped", "from": ["PID-5.2"], "transforms": [{"op": "title"}],
                            "confidence": 0.94, "proposed_by": "rules", "why": [...], "issues": [...],
                            "proposal": {...frozen copy of what was proposed...}},
        "direccion.codigo_postal": {"status": "no_data", "from": [], ...},
      },
      "unmatched": ["PID-11.4", ...],
      "approval": {"by": "Ana", "at": "...", "sha256": "..."}
    }

Field status, as in the hackathon design: "mapped" | "no_data" | "pending". Nothing pending may be approved.
Approval is tied to a hash of the exact decisions; editing one afterwards invalidates it. At
approval, every field whose decision differs from the original proposal gets `changed_by`
(traceability, docs/COMPLIANCE.md C9).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from .expected import Expected
from .records import Rows

STATUSES = ("mapped", "no_data", "pending")
DECISION = ("status", "from", "transforms", "default")
CONFIDENCE_KIND = "sin calibrar: ordena la revisión, no es una probabilidad"
COMPATIBLE_TYPES = {"integer": {"integer", "decimal"}, "decimal": {"integer", "decimal"}}


class ApprovalError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _decision(field: dict) -> dict:
    return {k: field[k] for k in DECISION if k in field}


def new(name: str, rows: Rows, expected: Expected, fields: dict[str, dict], proposed_by: str) -> dict:
    used = {c for f in fields.values() for c in f.get("from", [])}
    for f in fields.values():
        f.setdefault("proposed_by", proposed_by)
        f["proposal"] = _decision(f)
    return {
        "recipe": name,
        "status": "draft",
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "expected": expected.id,
        "source": {"file": rows.source, "format": rows.format,
                   "signature": sorted([c, rows.columns[c].dtype] for c in used),
                   # how each used column was documented: lets approved recipes teach later proposals
                   "described": {c: rows.columns[c].description or rows.columns[c].label for c in sorted(used)}},
        "confidence_kind": CONFIDENCE_KIND,
        "fields": fields,
        "unmatched": [c for c, f in rows.columns.items() if c not in used and f.dtype != "empty"],
        "approval": None,
    }


def plan_hash(recipe: dict) -> str:
    plan = {"expected": recipe["expected"], "format": recipe["source"]["format"],
            "fields": {t: _decision(f) for t, f in recipe["fields"].items()}}
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def problems(recipe: dict, expected: Expected) -> list[str]:
    """What blocks approval."""
    out = []
    if recipe["expected"] != expected.id:
        out.append(f"la receta es para {recipe['expected']}, no para {expected.id}")
    for t in expected.targets:
        f = recipe["fields"].get(t.path)
        if f is None:
            out.append(f"{t.path}: falta (todos los campos del destino deben aparecer)")
        elif f["status"] not in STATUSES:
            out.append(f"{t.path}: estado desconocido {f['status']!r}")
        elif f["status"] == "pending":
            out.append(f"{t.path}: pendiente ({'; '.join(f.get('issues') or ['sin decidir'])})")
        elif t.required and not f["from"] and "default" not in f:
            out.append(f"{t.path}: obligatorio sin origen ni valor por defecto")
        elif f["status"] == "mapped" and not f["from"] and "default" not in f:
            out.append(f"{t.path}: 'mapped' sin columna de origen")
    return out


def approve(recipe: dict, expected: Expected, by: str) -> dict:
    found = problems(recipe, expected)
    if not by.strip():
        found.append("hay que indicar quién aprueba")
    if found:
        raise ApprovalError(found)
    out = json.loads(json.dumps(recipe))
    for f in out["fields"].values():
        if _decision(f) != f.get("proposal"):
            f["changed_by"] = by.strip()
    out["status"] = "approved"
    out["approval"] = {"by": by.strip(), "at": dt.datetime.now().isoformat(timespec="seconds"),
                       "sha256": plan_hash(out)}
    return out


def verify(recipe: dict) -> None:
    if recipe.get("status") != "approved" or not recipe.get("approval"):
        raise ApprovalError([f"la receta '{recipe.get('recipe')}' no está aprobada"])
    if recipe["approval"]["sha256"] != plan_hash(recipe):
        raise ApprovalError([f"la receta '{recipe['recipe']}' se modificó después de aprobarse: hay que volver a aprobarla"])


def compatible(recipe: dict, rows: Rows, expected: Expected) -> list[str]:
    """Why `recipe` can't be reused for `rows` (empty = same structure; the engine still validates every value)."""
    why = []
    if recipe["expected"] != expected.id:
        why.append(f"otro destino ({recipe['expected']})")
    if recipe["source"]["format"] != rows.format:
        why.append(f"otro formato ({recipe['source']['format']})")
    for column, dtype in recipe["source"]["signature"]:
        f = rows.columns.get(column)
        if f is None:
            why.append(f"falta la columna {column}")
        elif f.dtype != dtype and f.dtype not in COMPATIBLE_TYPES.get(dtype, set()):
            why.append(f"{column} es {f.dtype}, la receta espera {dtype}")
    return why


def save(recipe: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find(folder: str | Path, rows: Rows, expected: Expected) -> list[tuple[Path, dict]]:
    """Approved, untampered recipes in `folder` that fit `rows`."""
    d = Path(folder)
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            r = load(p)
            verify(r)
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if not compatible(r, rows, expected):
            out.append((p, r))
    return out
