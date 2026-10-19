"""Deterministic transformation engine: approved driver + Dataset -> records for the contract.

No AI here. Every operation is declarative, versioned in the driver, and
reproducible. Each output record is validated against the contract; records
that break it are separated (not silently fixed) with the reason. The report
never contains data values, only positions and reasons (design doc §13).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .contract import Contract, TargetField
from .driver import verify
from .model import Dataset

CONNECTORS = {"de", "del", "la", "las", "los", "y", "e", "da", "do", "dos"}


class OpError(ValueError):
    pass


# --- operations ---------------------------------------------------------------------------------

def _title(s: str) -> str:
    out = []
    for i, word in enumerate(s.split(" ")):
        low = word.lower()
        if i and low in CONNECTORS:
            out.append(low)
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in word.split("-")))
    return " ".join(out)


def _date(v: str, fmt: str) -> str:
    try:
        if fmt == "iso":
            return dt.date.fromisoformat(v[:10]).isoformat()
        if fmt == "%Y%m%d":
            v = v[:8]
        return dt.datetime.strptime(v, fmt).date().isoformat()
    except ValueError:
        raise OpError(f"fecha no válida para el formato {fmt}") from None


def _number(v, decimal: str = "."):
    if isinstance(v, (int, float)):
        return v
    s = v.strip().replace(" ", "")
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        n = float(s)
    except ValueError:
        raise OpError("no es un número") from None
    return int(n) if n.is_integer() else n


def _phone(v: str, country: str) -> str:
    s = re.sub(r"[\s\-().]", "", v)
    if s.startswith("00"):
        s = "+" + s[2:]
    elif not s.startswith("+"):
        s = f"+{country}{s}"
    return s


def apply_value_op(op: dict, v):
    kind = op["op"]
    if kind == "date":
        return _date(v, op["from"])
    if kind == "number":
        return _number(v, op.get("decimal", "."))
    if kind == "scale":
        return round(_number(v) * op["factor"], 6)
    if kind == "map":
        return op["values"].get(v, v)
    if kind == "title":
        return _title(v)
    if kind == "phone":
        return _phone(v, op["country"])
    if kind == "pad":
        return str(v).zfill(op["width"])
    if kind == "constant":
        return op["value"]
    raise OpError(f"operación desconocida {kind!r}")


def _cast(t: TargetField, v):
    if v is None:
        return None
    if t.type == "string":
        return v if isinstance(v, str) else str(v)
    if t.type in ("number", "integer"):
        n = _number(v)
        if t.type == "integer" and isinstance(n, float):
            raise OpError("no es un entero")
        return n
    if t.type == "boolean":
        if isinstance(v, bool):
            return v
        low = str(v).strip().lower()
        if low in ("true", "1", "si", "sí", "s", "yes", "y"):
            return True
        if low in ("false", "0", "no", "n"):
            return False
        raise OpError("no es booleano")
    return v


# --- joins ----------------------------------------------------------------------------------------

def _related(ds: Dataset, driver: dict) -> list[tuple[dict, dict[str, list[dict]]]]:
    root = driver["source"]["root"]
    join = driver["source"]["join"]
    rows = ds.tables.get(root, [])
    others = {e: recs for e, recs in ds.tables.items() if e != root}
    out = []
    for row in rows:
        linked: dict[str, list[dict]] = {}
        if join == "hl7_message":
            linked = {e: [r for r in recs if r.get("_message") == row.get("_message")] for e, recs in others.items()}
        elif join == "fhir_reference":
            ref = f"{root}/{row.get('id')}"
            linked = {e: [r for r in recs if any(k.endswith(".reference") and v == ref for k, v in r.items())]
                      for e, recs in others.items()}
        out.append((row, linked))
    return out


def _values(src: dict, root: str, row: dict, linked: dict[str, list[dict]]) -> list:
    recs = [row] if src["entity"] == root else linked.get(src["entity"], [])
    out = []
    for r in recs:
        v = r.get(src["path"])
        if isinstance(v, list):
            out += [x for x in v if x not in (None, "")]
        elif v not in (None, ""):
            out.append(v)
    return out


# --- run ----------------------------------------------------------------------------------------

@dataclass
class RunResult:
    records: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # {"record": i, "errors": [...]} without the data
    report: dict = field(default_factory=dict)


def _set(out: dict, path: str, value) -> None:
    node = out
    *parents, leaf = path.split(".")
    for p in parents:
        node = node.setdefault(p, {})
    node[leaf] = value


def map_record(row: dict, linked: dict, driver: dict, contract: Contract) -> tuple[dict, list[dict]]:
    root = driver["source"]["root"]
    out: dict = {}
    errors: list[dict] = []
    for m in driver["mappings"]:
        t = contract.get(m["target"])
        try:
            if m["sources"]:
                per_source = [_values(s, root, row, linked) for s in m["sources"]]
                ops = list(m["ops"])
                if ops and ops[0]["op"] == "concat":
                    sep = ops.pop(0)["sep"]
                    parts = [vals[0] for vals in per_source if vals]
                    values = [sep.join(str(p) for p in parts)] if parts else []
                else:
                    values = per_source[0]
                for op in ops:
                    if op["op"] == "first":
                        values = values[:1]
                    elif op["op"] == "join":
                        values = [op["sep"].join(str(v) for v in values)] if values else []
                    else:
                        values = [apply_value_op(op, v) for v in values]
                if len(values) > 1:
                    raise OpError("varios valores en origen y ninguna regla (first/join)")
                value = values[0] if values else m.get("default")
            else:
                value = m.get("default")
            value = _cast(t, value)
        except OpError as e:
            errors.append({"target": t.path, "reason": str(e)})
            continue
        problem = contract.check(t, value)
        if problem:
            errors.append({"target": t.path, "reason": problem})
            continue
        if value is None and t.on_missing == "omit":
            continue
        _set(out, t.path, value)
    return out, errors


def run(ds: Dataset, driver: dict, contract: Contract) -> RunResult:
    verify(driver)
    if driver["contract"] != contract.id:
        raise ValueError(f"el driver es para {driver['contract']}, no para {contract.id}")
    result = RunResult()
    empty = {t.path: 0 for t in contract.fields}
    for i, (row, linked) in enumerate(_related(ds, driver)):
        rec, errors = map_record(row, linked, driver, contract)
        if errors:
            result.rejected.append({"record": i, "errors": errors})
        else:
            result.records.append(rec)
            for t in contract.fields:
                node = rec
                for part in t.path.split("."):
                    node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    empty[t.path] += 1
    result.report = {
        "driver": driver["driver"], "approved_by": driver["approval"]["by"],
        "plan_sha256": driver["approval"]["plan_sha256"], "contract": contract.id, "source": ds.source,
        "processed": len(result.records) + len(result.rejected), "accepted": len(result.records),
        "rejected": len(result.rejected), "empty_fields": {k: v for k, v in empty.items() if v},
        "errors": [{"record": r["record"], **e} for r in result.rejected for e in r["errors"]],
    }
    return result
