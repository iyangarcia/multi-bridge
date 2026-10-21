"""The engine: approved recipe + flat rows -> output records. No AI, no joins, no guessing.

For each row and each target field: take the values of the `from` columns, apply the
transforms in order, check the result against EXPECTED. A row that breaks a rule is set
aside with the reason (never silently fixed). The report has positions and reasons only,
never data values (docs/COMPLIANCE.md C11).

Transforms (hackathon list + format conversions):
    (none)          copy the value as is
    date            {"from": "%d/%m/%Y" | "%Y%m%d" | "iso"}        -> "aaaa-mm-dd"
    translate       {"values": {"H": "male", "M": "female"}}       unknown values pass through, then get validated
    join_columns    {"sep": " "}                                    several `from` columns -> one value
    split           {"sep": " ", "index": 0}                        one part of a value
    number          {"decimal": "," | "."}
    scale           {"factor": 0.001}
    phone           {"country": "34"}                               -> "+34600000000"
    pad             {"width": 5}                                    "3001" -> "03001"
    title           "PABLO MARTINEZ" -> "Pablo Martinez"
    first / join_values {"sep": "; "}                               several values in one cell
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .expected import Expected, Target
from .recipe import verify
from .records import Rows

CONNECTORS = {"de", "del", "la", "las", "los", "y", "e", "da", "do", "dos"}


class TransformError(ValueError):
    pass


def _title(s: str) -> str:
    parts = s.split(" ")
    return " ".join(p.lower() if i and p.lower() in CONNECTORS
                    else "-".join(x[:1].upper() + x[1:].lower() for x in p.split("-"))
                    for i, p in enumerate(parts))


def _number(v, decimal: str = "."):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v).strip().replace(" ", "")
    if decimal == "," and "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        n = float(s)
    except ValueError:
        raise TransformError("no es un número") from None
    return int(n) if n.is_integer() else n


def _date(v: str, fmt: str) -> str:
    try:
        if fmt == "iso":
            return dt.date.fromisoformat(v[:10]).isoformat()
        return dt.datetime.strptime(v[:8] if fmt == "%Y%m%d" else v, fmt).date().isoformat()
    except ValueError:
        raise TransformError(f"fecha no válida para el formato {fmt}") from None


def _phone(v: str, country: str) -> str:
    s = re.sub(r"[\s\-().]", "", v)
    return "+" + s[2:] if s.startswith("00") else s if s.startswith("+") else f"+{country}{s}"


def _split(v: str, sep: str, index: int) -> str | None:
    parts = [p for p in v.split(sep) if p]
    return parts[index] if -len(parts) <= index < len(parts) else None


VALUE_TRANSFORMS = {
    "date": lambda v, t: _date(v, t["from"]),
    "translate": lambda v, t: t["values"].get(v, v),
    "split": lambda v, t: _split(v, t.get("sep", " "), t.get("index", 0)),
    "number": lambda v, t: _number(v, t.get("decimal", ".")),
    "scale": lambda v, t: round(_number(v) * t["factor"], 6),
    "phone": lambda v, t: _phone(v, t["country"]),
    "pad": lambda v, t: str(v).zfill(t["width"]),
    "title": lambda v, t: _title(v),
}


def _cast(target: Target, v):
    if v is None or target.type == "date":
        return v
    if target.type == "string":
        return v if isinstance(v, str) else str(v)
    if target.type in ("number", "integer"):
        return _number(v)
    if target.type == "boolean" and not isinstance(v, bool):
        low = str(v).strip().lower()
        if low not in ("true", "false", "1", "0", "si", "sí", "no"):
            raise TransformError("no es booleano")
        return low in ("true", "1", "si", "sí")
    return v


def field_value(row: dict, spec: dict, target: Target):
    cells = [row.get(c) for c in spec["from"]]
    columns = [c if isinstance(c, list) else [] if c is None else [c] for c in cells]
    transforms = list(spec["transforms"])
    if transforms and transforms[0]["op"] == "join_columns":
        sep = transforms.pop(0)["sep"]
        parts = [str(vals[0]) for vals in columns if vals]
        values = [sep.join(parts)] if parts else []
    else:
        values = columns[0] if columns else []
    for t in transforms:
        if t["op"] == "first":
            values = values[:1]
        elif t["op"] == "join_values":
            values = [t["sep"].join(str(v) for v in values)] if values else []
        elif t["op"] in VALUE_TRANSFORMS:
            values = [x for x in (VALUE_TRANSFORMS[t["op"]](v, t) for v in values) if x is not None]
        else:
            raise TransformError(f"transformación desconocida {t['op']!r}")
    if len(values) > 1:
        if target.multiple == "join":
            values = ["; ".join(str(v) for v in values)]
        elif target.multiple == "first":
            values = values[:1]
        else:
            raise TransformError("varios valores en origen y ninguna regla (first / join_values)")
    return _cast(target, values[0] if values else spec.get("default"))


@dataclass
class Result:
    records: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)   # {"row": i, "errors": [{"field", "reason"}]}, no values
    report: dict = field(default_factory=dict)


def _set(out: dict, path: str, value) -> None:
    *parents, leaf = path.split(".")
    for p in parents:
        out = out.setdefault(p, {})
    out[leaf] = value


def run(rows: Rows, recipe: dict, expected: Expected) -> Result:
    verify(recipe)
    if recipe["expected"] != expected.id:
        raise ValueError(f"la receta es para {recipe['expected']}, no para {expected.id}")
    result = Result()
    empty = {t.path: 0 for t in expected.targets}
    for i, row in enumerate(rows.rows):
        out, errors = {}, []
        for t in expected.targets:
            spec = recipe["fields"][t.path]
            try:
                value = field_value(row, spec, t)
            except TransformError as e:
                errors.append({"field": t.path, "reason": str(e)})
                continue
            problem = Expected.check(t, value)
            if problem:
                errors.append({"field": t.path, "reason": problem})
                continue
            if value is None:
                empty[t.path] += 1
                if t.on_missing == "omit":
                    continue
            _set(out, t.path, value)
        if errors:
            result.rejected.append({"row": i, "errors": errors})
        else:
            result.records.append(out)
    result.report = {
        "recipe": recipe["recipe"], "approved_by": recipe["approval"]["by"], "sha256": recipe["approval"]["sha256"],
        "expected": expected.id, "source": rows.source, "rows": len(rows.rows),
        "accepted": len(result.records), "rejected": len(result.rejected),
        "empty_fields": {k: v for k, v in empty.items() if v},
        "errors": [{"row": r["row"], **e} for r in result.rejected for e in r["errors"]],
    }
    return result
