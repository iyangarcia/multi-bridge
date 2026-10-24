"""The engine: approved recipe + flat rows -> output items. No AI, no joins, no guessing.

For each row and each target field: take the values of the `from` columns, apply the
transforms in order, check the result against EXPECTED. A row that breaks a rule is set
aside with the reason (never silently fixed). The report has positions and reasons only,
never data values (docs/COMPLIANCE.md C11).

Cardinality (output.py has the item shape):
    one row -> one item           the default
    many rows -> one item         the destination's "$group_by": rows with the same key value
                                  become one item; fields outside the repeated group must agree
                                  across those rows, fields inside it give one entry per row
    one row -> several entries    a target that takes a list (example ["a", "b"]), or a template
                                  with several parts per item (a standard message writer)
Custom fields: the recipe's "extras" say which unmatched source columns are carried
through (copied as they are into the item's extras) and which were dropped, by whom.

Transforms (hackathon list + format conversions):
    (none)          copy the value as is
    date            {"from": "%d/%m/%Y" | "%Y%m%d" | "iso"}        -> "aaaa-mm-dd"
    translate       {"values": {"H": "male", "M": "female"}}       unknown values pass through, then get validated
    join_columns    {"sep": " "}                                    several `from` columns -> one value
    split           {"sep": " ", "index": 0}                        one part of a value
    split_values    {"sep": ";"}                                    "HTA; DLP" -> ["HTA", "DLP"] (a target that takes a list)
    name_part       {"part": "given" | "family", "surnames": 2}     "Lucía María Álvarez Castro" -> "Lucía María" /
                                                                    "Álvarez Castro" (particles such as "de la" stay
                                                                    with their surname)
    number          {"decimal": "," | "."}
    scale           {"factor": 0.001}
    phone           {"country": "34"}                               -> "+34600000000"
    pad             {"width": 5}                                    "3001" -> "03001"
    title           "PABLO MARTINEZ" -> "Pablo Martinez"
    first / join_values {"sep": "; "}                               several values in one cell
A target that takes a list and has several `from` columns gets the values of all of them, in order.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .expected import Expected, Target
from .output import EXTRAS, nest
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


def _date(v: str, fmt: str | list[str]) -> str:
    """`fmt` may be a list: a column that mixes date shapes; the formats are tried in the listed order."""
    for f in [fmt] if isinstance(fmt, str) else fmt:
        try:
            if f == "iso":
                return dt.date.fromisoformat(v[:10]).isoformat()
            return dt.datetime.strptime(v[:8] if f == "%Y%m%d" else v, f).date().isoformat()
        except ValueError:
            continue
    raise TransformError(f"fecha no válida para el formato {fmt}")


def _phone(v: str, country: str) -> str:
    s = re.sub(r"[\s\-().]", "", v)
    return "+" + s[2:] if s.startswith("00") else s if s.startswith("+") else f"+{country}{s}"


def _split(v: str, sep: str, index: int) -> str | None:
    parts = [p for p in v.split(sep) if p]
    return parts[index] if -len(parts) <= index < len(parts) else None


def _name_part(v: str, part: str, surnames: int):
    """Given name(s) or surnames of a full name written "given... surname surname"."""
    words = str(v).split()
    end = len(words)
    for _ in range(surnames):
        if end <= 1:
            break
        end -= 1
        while end > 1 and words[end - 1].lower() in CONNECTORS:
            end -= 1    # "de la Fuente": the particles belong to the surname
    given, family = " ".join(words[:end]), " ".join(words[end:])
    return (given if part == "given" else family) or None


VALUE_TRANSFORMS = {
    "date": lambda v, t: _date(v, t["from"]),
    "translate": lambda v, t: t["values"].get(v, v),
    "split": lambda v, t: _split(v, t.get("sep", " "), t.get("index", 0)),
    "number": lambda v, t: _number(v, t.get("decimal", ".")),
    "scale": lambda v, t: round(_number(v) * t["factor"], 6),
    "phone": lambda v, t: _phone(v, t["country"]),
    "pad": lambda v, t: str(v).zfill(t["width"]),
    "title": lambda v, t: _title(v),
    "name_part": lambda v, t: _name_part(v, t["part"], t.get("surnames", 2)),
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
    elif target.multiple == "list":
        values = [v for vals in columns for v in vals]     # several columns -> one list, in order
    else:
        values = columns[0] if columns else []
    for t in transforms:
        if t["op"] == "split_values":
            values = [p.strip() for v in values for p in str(v).split(t.get("sep", ";")) if p.strip()]
        elif t["op"] == "first":
            values = values[:1]
        elif t["op"] == "join_values":
            values = [t["sep"].join(str(v) for v in values)] if values else []
        elif t["op"] in VALUE_TRANSFORMS:
            values = [x for x in (VALUE_TRANSFORMS[t["op"]](v, t) for v in values) if x is not None]
        else:
            raise TransformError(f"transformación desconocida {t['op']!r}")
    if target.multiple == "list":
        out = [_cast(target, v) for v in values]
        return out if out else ([] if spec.get("default") is None else [_cast(target, spec["default"])])
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
    records: list[dict] = field(default_factory=list)    # nested, the JSON view of each item
    rejected: list[dict] = field(default_factory=list)   # {"row": i, "errors": [{"field", "reason"}]}, no values
    report: dict = field(default_factory=dict)
    items: list[dict] = field(default_factory=list)      # flat items, what the writers take

    def write(self, expected: Expected) -> bytes:
        """The output in the destination's own format."""
        from . import formats
        return formats.get(expected.format).write(self.items, expected)


def _same(a, b) -> bool:
    return a == b or (a in (None, "", []) and b in (None, "", []))


def _group(flat_rows: list[tuple[int, dict]], expected: Expected) -> tuple[list[dict], list[dict]]:
    """Many rows -> one item. Returns (items, rejected)."""
    groups = {g: [t.path for t in expected.targets if t.group == g] for g in expected.groups}
    outside = [t.path for t in expected.targets if not t.group]
    buckets: dict[str, list[tuple[int, dict]]] = {}
    rejected = []
    for i, flat in flat_rows:
        if expected.group_by:
            key = flat.get(expected.group_by)
            if key in (None, ""):
                rejected.append({"row": i, "errors": [{"field": expected.group_by, "reason": "sin valor en el campo que agrupa"}]})
                continue
            buckets.setdefault(str(key), []).append((i, flat))
        else:
            buckets[str(i)] = [(i, flat)]
    items = []
    for members in buckets.values():
        first = members[0][1]
        clash = [p for p in outside if any(not _same(first.get(p), f.get(p)) for _, f in members[1:])]
        if clash:
            rejected += [{"row": i, "errors": [{"field": p, "reason": "valores distintos en filas del mismo grupo"}
                                               for p in clash]} for i, _ in members]
            continue
        item = {p: first.get(p) for p in outside if p in first}
        for g, paths in groups.items():
            subs = [{p: f.get(p) for p in paths if p in f} for _, f in members]
            item[g] = [s for s in subs if any(v not in (None, []) for v in s.values())]
        extras: dict = {}
        for _, f in members:
            for k, v in (f.get(EXTRAS) or {}).items():
                extras.setdefault(k, [])
                if v not in (None, "") and v not in extras[k]:
                    extras[k].append(v)
        if extras:
            item[EXTRAS] = {k: (v[0] if len(v) == 1 else v or None) for k, v in extras.items()}
        items.append(item)
    return items, rejected


def run(rows: Rows, recipe: dict, expected: Expected) -> Result:
    verify(recipe)
    if recipe["expected"] != expected.id:
        raise ValueError(f"la receta es para {recipe['expected']}, no para {expected.id}")
    result = Result()
    empty = {t.path: 0 for t in expected.targets}
    extras = recipe.get("extras") or {}
    carried = extras.get("carry") or []
    flat_rows: list[tuple[int, dict]] = []
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
            if value is None or value == []:
                empty[t.path] += 1
                if t.on_missing == "omit":
                    continue
            out[t.path] = value
        if carried:
            out[EXTRAS] = {c: row.get(c) for c in carried if row.get(c) not in (None, "", [])}
        if errors:
            result.rejected.append({"row": i, "errors": errors})
        else:
            flat_rows.append((i, out))
    grouped = bool(expected.group_by or expected.groups)
    if grouped:
        result.items, more = _group(flat_rows, expected)
        result.rejected = sorted(result.rejected + more, key=lambda r: r["row"])
    else:
        result.items = [flat for _, flat in flat_rows]
    result.records = [nest(item, expected) for item in result.items]
    result.report = {
        "recipe": recipe["recipe"], "approved_by": recipe["approval"]["by"], "sha256": recipe["approval"]["sha256"],
        "expected": expected.id, "source": rows.source, "rows": len(rows.rows),
        "accepted": len(result.records), "rejected": len(result.rejected),
        "empty_fields": {k: v for k, v in empty.items() if v},
        "errors": [{"row": r["row"], **e} for r in result.rejected for e in r["errors"]],
    }
    if grouped:
        result.report["accepted"] = len(rows.rows) - len(result.rejected)
        result.report["items"] = len(result.items)
    if extras:   # unmatched source fields: what went through and what was dropped, and by whom (C9)
        result.report["custom_fields"] = {"carried": list(carried), "dropped": list(extras.get("drop") or []),
                                          "by": extras.get("by")}
    return result
