"""What the AI model is allowed to see about a source file and the destination (COMPLIANCE C4, C6).

Default deny: a column's real values are shown only if it is *cleared*, meaning a short,
non-sensitive category list like H/M, A+/0- or I/E. Every other column is described
without its content:

    masked samples   "FERNANDEZ ALVAREZ" -> "XXXXXXXXX XXXXXXX", "HC-7781" -> "XX-9999",
                     "14/02/1978" -> "99/99/9999": the shape (case, length, digits, separators)
                     without the content
    numeric summary  for non-sensitive measurements (weights, heights): min / median / max
    concepts         for diagnosis text: how many values the terminology recognised, never the text

This is pseudonymisation, not anonymisation (GDPR recital 26): the view is for a model running
on this machine. A remote model (Jev) would get even less (COMPLIANCE C5).
"""

from __future__ import annotations

import re
import statistics

from .concepts import _flat
from .expected import Expected
from .model import Field
from .records import Rows

MAX_SAMPLES = 3
MAX_CATEGORIES = 12


def mask(value: str) -> str:
    return "".join("9" if c.isdigit() else ("X" if c.isupper() else "x") if c.isalpha() else c for c in str(value))


def cleared(f: Field, flat: list[str]) -> bool:
    """May the model see this column's real values? Only short, non-identifying categories."""
    return (f.kind == "categorical" and not f.sensitive and len(set(flat)) <= MAX_CATEGORIES
            and all(len(v) <= 20 for v in flat))


def _numeric_summary(f: Field, flat: list[str]) -> dict | None:
    if f.sensitive or f.dtype not in ("integer", "decimal"):
        return None
    if f.dtype == "integer" and any(len(v.lstrip("+-")) > 3 for v in flat):
        return None  # 5-digit codes (postal codes, IDs) are not measurements
    nums = [float(v.replace(",", ".")) for v in flat if re.fullmatch(r"[+-]?\d+([.,]\d+)?", v)]
    if not nums:
        return None
    return {"min": round(min(nums), 1), "median": round(statistics.median(nums), 1), "max": round(max(nums), 1)}


def column_view(name: str, f: Field, values: list) -> dict:
    flat = _flat(values)
    item = {"column": name, "entity": f.entity, "description": f.description or None, "type": f.dtype,
            "format": f.format, "unit": f.unit, "kind": f.kind, "custom": f.custom,
            "empty_ratio": round(sum(v in (None, "", []) for v in values) / len(values), 2) if values else 1.0,
            "several_values": any(isinstance(v, list) for v in values)}
    if cleared(f, flat):
        item["values"] = sorted(set(flat))
    elif (summary := _numeric_summary(f, flat)) is not None:
        item["numbers"] = summary
    elif f.concepts:
        item["concepts"] = {"systems": f.concepts["systems"], "recognised": f.concepts["recognised"],
                            "of": f.concepts["values"]}
    else:
        item["masked_samples"] = list(dict.fromkeys(mask(v) for v in flat))[:MAX_SAMPLES]
    return {k: v for k, v in item.items() if v not in (None, False)}


def source_view(rows: Rows) -> dict:
    return {"format": rows.format, "rows": len(rows.rows),
            "columns": [column_view(c, f, rows.values(c)) for c, f in rows.columns.items() if f.dtype != "empty"]}


def target_view(expected: Expected) -> list[dict]:
    """The destination fields. Example values are masked too: an example file could hold a real record."""
    out = []
    for t in expected.targets:
        ex = t.example
        if isinstance(ex, str) and not (t.enum and ex in t.enum):
            ex = mask(ex)
        item = {"target": t.path, "type": t.type, "description": t.description or None, "required": t.required,
                "allowed": t.enum, "unit": t.unit, "example": ex}
        out.append({k: v for k, v in item.items() if v not in (None, False)})
    return out
