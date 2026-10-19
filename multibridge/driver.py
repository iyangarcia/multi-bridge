"""Driver lifecycle: draft -> approved (by a person) -> reusable.

A driver is plain JSON: the reviewed mapping plan plus approval metadata.
Approval is tied to a hash of the exact plan (design doc §11): edit one
mapping after approving and the engine refuses to run it until re-approved.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from .contract import Contract
from .model import Dataset


class ApprovalError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


COMPATIBLE_TYPES = {"integer": {"integer", "decimal"}, "decimal": {"integer", "decimal"}}


def plan_hash(driver: dict) -> str:
    plan = {"contract": driver["contract"],
            "source": {k: driver["source"][k] for k in ("format", "root", "join")},
            "mappings": [{k: m[k] for k in ("target", "status", "sources", "ops") if k in m} | (
                {"default": m["default"]} if "default" in m else {}) for m in driver["mappings"]]}
    raw = json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def problems(driver: dict, contract: Contract) -> list[str]:
    """What blocks approval."""
    out = []
    if driver["contract"] != contract.id:
        out.append(f"el driver es para {driver['contract']}, no para {contract.id}")
    targets = {m["target"]: m for m in driver["mappings"]}
    for t in contract.fields:
        m = targets.get(t.path)
        if m is None:
            out.append(f"{t.path}: falta en el plan (todas las entidades de EXPECTED deben aparecer)")
        elif m["status"] == "pending":
            out.append(f"{t.path}: pendiente de decisión ({'; '.join(m.get('issues') or [])})")
        elif t.required and not m["sources"] and "default" not in m:
            out.append(f"{t.path}: obligatorio sin origen ni valor por defecto")
    return out


def approve(driver: dict, contract: Contract, by: str) -> dict:
    found = problems(driver, contract)
    if found:
        raise ApprovalError(found)
    if not by.strip():
        raise ApprovalError(["hay que indicar quién aprueba"])
    approved = dict(driver)
    approved["status"] = "approved"
    approved["approval"] = {"by": by.strip(), "at": dt.datetime.now().isoformat(timespec="seconds"),
                            "plan_sha256": plan_hash(driver)}
    return approved


def verify(driver: dict) -> None:
    """Refuse drafts and drivers edited after approval."""
    if driver.get("status") != "approved" or "approval" not in driver:
        raise ApprovalError([f"el driver '{driver.get('driver')}' no está aprobado"])
    if driver["approval"]["plan_sha256"] != plan_hash(driver):
        raise ApprovalError([f"el driver '{driver['driver']}' se modificó después de aprobarse: hay que volver a aprobarlo"])


def compatible(driver: dict, ds: Dataset, contract: Contract) -> list[str]:
    """Why `driver` can't be reused for `ds` (empty list = structurally compatible, design doc §10)."""
    why = []
    if driver["contract"] != contract.id:
        why.append(f"otro contrato ({driver['contract']})")
    if driver["source"]["format"] != ds.format:
        why.append(f"otro formato ({driver['source']['format']})")
    have = {(f.entity, f.path): f.dtype for f in ds.fields}
    for entity, path, dtype in driver["source"]["signature"]:
        got = have.get((entity, path))
        if got is None:
            why.append(f"falta el campo {entity}:{path}")
        elif got != dtype and got not in COMPATIBLE_TYPES.get(dtype, set()):
            why.append(f"{entity}:{path} es {got}, el driver espera {dtype}")
    return why


def save(driver: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(driver, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_compatible(drivers_dir: str | Path, ds: Dataset, contract: Contract) -> list[tuple[Path, dict]]:
    d = Path(drivers_dir)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            drv = load(p)
            verify(drv)
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if not compatible(drv, ds, contract):
            out.append((p, drv))
    return out
