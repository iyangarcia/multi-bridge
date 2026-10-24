"""Grade a proposal against an evaluation case, and calibrate confidences.

A field is graded by its output, not by its column name: the proposal's columns and transforms
are run on every source row and compared with the correct values. So a column that holds the
same data under another name is right, and a right column with a wrong transform is wrong.

    right    mapped and every value comes out right, or "no data" where the file has none
    pending  left for a human (costs time, not safety); `accepted` says whether taking the
             proposed column as it is would have been right
    missed   "no data" where the file has the data (incomplete, but nothing false is written)
    wrong    mapped, and some value comes out wrong or invented: a reviewer must catch it.
             `silent` says whether a wrong value would pass every rule of the destination; if not,
             the engine sets those rows aside with the reason (loud, not silent)

`oracle` runs the true columns with the transforms the rules would choose for them: it tells
column mistakes apart from transform mistakes.
"""

from __future__ import annotations

import math

from multibridge import packs
from multibridge.engine import TransformError, field_value
from multibridge.expected import Expected
from multibridge.matcher import transforms_for
from multibridge.parsers import parse_bytes
from multibridge.records import Rows, to_rows

from . import Case

BANDS = [0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]


def read(case: Case) -> tuple[Rows, Expected]:
    rows = to_rows(parse_bytes(case.data, case.name))
    if len(rows.rows) != len(case.values):
        raise AssertionError(f"{case.label}: {len(rows.rows)} filas leídas, {len(case.values)} generadas")
    return rows, Expected.load(case.destination)


def _same(got, want) -> bool:
    if want in (None, "", []):
        return got in (None, "", [])
    if isinstance(want, (int, float)) and isinstance(got, (int, float)) and not isinstance(got, bool):
        return math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9)
    return got == want


def check(rows: Rows, spec: dict, t, case: Case) -> str:
    """"ok", "caught" (some rows fail a transform or the destination's rules, so the engine sets them
    aside: loud) or "silent" (some row gets a wrong value that passes every rule: the dangerous one)."""
    out = "ok"
    for row, want in zip(rows.rows, case.values):
        try:
            got = field_value(row, spec, t)
        except TransformError:
            out = "caught"
            continue
        if want[t.path] is None and got in (None, "", []):
            continue
        if _same(got, want[t.path]):
            continue
        if Expected.check(t, got) is None:
            return "silent"
        out = "caught"
    return out


def correct(rows: Rows, spec: dict, t, case: Case) -> bool:
    return check(rows, spec, t, case) == "ok"


def grade(case: Case, draft: dict, rows: Rows | None = None, expected: Expected | None = None) -> list[dict]:
    if rows is None or expected is None:
        rows, expected = read(case)
    pack = packs.get(expected.pack)
    out = []
    for t in expected.targets:
        f = draft["fields"][t.path]
        has = any(v[t.path] not in (None, "", []) for v in case.values)
        cols = f.get("from") or []
        g = {"case": case.label, "domain": case.domain, "format": case.format, "target": t.path,
             "status": f["status"], "from": cols, "truth": case.truth.get(t.path, []),
             "confidence": f.get("confidence"), "accepted": None, "oracle": None, "silent": None}
        if f["status"] == "mapped":      # (mapped to a constant, with no column, is graded the same way)
            result = check(rows, f, t, case)
            g["outcome"] = "right" if result == "ok" else "wrong"
            g["silent"] = result == "silent" if result != "ok" else None
        elif f["status"] == "pending":
            g["outcome"] = "pending"
            g["accepted"] = correct(rows, f, t, case) if cols else not has
        else:
            g["outcome"] = "missed" if has else "right"
        if has and g["truth"]:
            transforms, _, _ = transforms_for(rows, g["truth"], t, pack)
            g["oracle"] = correct(rows, {"from": g["truth"], "transforms": transforms}, t, case)
        out.append(g)
    return out


# --- calibration -------------------------------------------------------------------------------------

def points(graded: list[dict]) -> list[tuple[float, bool]]:
    """(confidence, right if accepted as proposed) for every field the proposal gave a column."""
    out = []
    for g in graded:
        if g["confidence"] is None or not g["from"]:
            continue
        ok = g["outcome"] == "right" if g["outcome"] in ("right", "wrong") else g["accepted"]
        out.append((float(g["confidence"]), bool(ok)))
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a rate of k in n."""
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def bands(pts: list[tuple[float, bool]], edges: list[float] = BANDS) -> list[dict]:
    """Per score band: how many proposals, how many right, and the rate with its interval."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        inside = [ok for c, ok in pts if lo <= c < hi or (hi == edges[-1] and c == hi)]
        k, n = sum(inside), len(inside)
        low, high = wilson(k, n)
        out.append({"low": lo, "high": hi, "n": n, "right": k, "rate": round(k / n, 3) if n else None,
                    "interval": [round(low, 3), round(high, 3)]})
    return out


def fit(table: list[dict]) -> list[dict]:
    """Make the measured rates non-decreasing with the score (pool adjacent violators, weighted by n):
    a higher score must never mean a lower measured rate. Empty bands take no part."""
    blocks = [[b["right"], b["n"], [i]] for i, b in enumerate(table) if b["n"]]
    merged: list[list] = []
    for blk in blocks:
        merged.append(blk)
        while len(merged) > 1 and merged[-2][0] / merged[-2][1] > merged[-1][0] / merged[-1][1]:
            k, n, idx = merged.pop()
            merged[-1][0] += k
            merged[-1][1] += n
            merged[-1][2] += idx
    out = [dict(b, calibrated=None) for b in table]
    for k, n, idx in merged:
        for i in idx:
            out[i]["calibrated"] = round(k / n, 3)
    return out


def expected_error(table: list[dict], pts: list[tuple[float, bool]]) -> float | None:
    """How far, on average, the calibrated rates are from what really happened on `pts` (weighted
    by how many proposals fall in each band): the expected calibration error."""
    held = bands(pts, [b["low"] for b in table] + [table[-1]["high"]])
    total = sum(b["n"] for b in held)
    if not total:
        return None
    err = sum(b["n"] * abs((b["right"] / b["n"]) - (c["calibrated"] or 0)) for b, c in zip(held, table) if b["n"])
    return round(err / total, 3)
