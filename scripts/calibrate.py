"""Phase 9: measure the proposers on the generated evaluation set and calibrate their confidences.

    .venv/Scripts/python scripts/calibrate.py                         # rules, 600 + 600 files
    .venv/Scripts/python scripts/calibrate.py rules qwen3:8b --cases 60   # also the local model (Ollama must run)

Two disjoint sets of generated files (evalset/), spread evenly over every domain and format:
    fit       seeds 1000...  the measured hit rate per confidence band is fitted on these
    held-out  seeds 2000...  the fitted rates are checked on files they have never seen
(Seeds 0–299 were used while fixing the matcher; neither set reuses them.)

Writes docs/CALIBRATION.md and multibridge/calibration.json (the table the web app shows next to each
confidence: "in tests, proposals at this level were right N in 100"). Synthetic data only (C1).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evalset import cases  # noqa: E402
from evalset.grade import bands, expected_error, fit, grade, points, read  # noqa: E402
from multibridge.ai.ollama import OllamaUnavailable  # noqa: E402
from multibridge.proposer import propose  # noqa: E402

EDGES = [0.6, 0.7, 0.8, 0.9, 1.0]
OUTCOMES = ("right", "pending", "missed", "wrong")


def measure(model: str, n: int, start: int) -> tuple[list[dict], float, int]:
    graded, seconds, failed = [], 0.0, 0
    for case in cases(n, start):
        rows, expected = read(case)
        t = time.monotonic()
        try:
            draft = propose(rows, expected, model=model)
        except OllamaUnavailable as e:
            print(f"{model}: {e}", file=sys.stderr)
            failed += 1
            continue
        seconds += time.monotonic() - t
        graded += grade(case, draft, rows, expected)
    return graded, seconds, failed


def outcome_table(graded: list[dict]) -> list[str]:
    counts = collections.defaultdict(collections.Counter)
    silent = collections.Counter()
    oracle = collections.defaultdict(collections.Counter)
    for g in graded:
        key = (g["domain"], g["format"])
        counts[key][g["outcome"]] += 1
        silent[key] += bool(g["silent"])
        if g["oracle"] is not None:
            oracle[key][g["oracle"]] += 1
    lines = ["| domain | format | fields | right | pending | missed | wrong | of which silent | oracle |",
             "|---|---|---|---|---|---|---|---|---|"]
    total, total_silent, total_oracle = collections.Counter(), 0, collections.Counter()
    for key in sorted(counts):
        c, o = counts[key], oracle[key]
        n = sum(c.values())
        total += c
        total_silent += silent[key]
        total_oracle += o
        lines.append(f"| {key[0]} | {key[1]} | {n} | " + " | ".join(f"{c[x]} ({c[x] / n:.0%})" for x in OUTCOMES)
                     + f" | {silent[key]} | {o[True]}/{o[True] + o[False]} |")
    n = sum(total.values())
    lines.append(f"| **all** | | {n} | " + " | ".join(f"{total[x]} ({total[x] / n:.0%})" for x in OUTCOMES)
                 + f" | {total_silent} | {total_oracle[True]}/{total_oracle[True] + total_oracle[False]} |")
    return lines


def band_table(table: list[dict], held: list[dict]) -> list[str]:
    lines = ["| score | fit: proposals | fit: right | 95% interval | calibrated | held-out: proposals | held-out: right |",
             "|---|---|---|---|---|---|---|"]
    for b, h in zip(table, held):
        rate = f"{b['rate']:.1%}" if b["rate"] is not None else "—"
        cal = f"{b['calibrated']:.1%}" if b["calibrated"] is not None else "—"
        hr = f"{h['rate']:.1%}" if h["rate"] is not None else "—"
        lines.append(f"| {b['low']:.2f}–{b['high']:.2f} | {b['n']} | {rate} | {b['interval'][0]:.1%}–{b['interval'][1]:.1%} "
                     f"| {cal} | {h['n']} | {hr} |")
    return lines


def mistakes(graded: list[dict], limit: int = 25) -> list[str]:
    out = []
    for g in graded:
        if g["outcome"] == "wrong" or (g["outcome"] == "pending" and g["accepted"] is False and g["from"]):
            kind = ("wrong, silent" if g["silent"] else "wrong, set aside by the checks") if g["outcome"] == "wrong" \
                else "pending, its column would be wrong"
            out.append(f"- `{g['case']}` **{g['target']}** ← {' + '.join(g['from'])} ({g['confidence']}): {kind}; "
                       f"right: {' + '.join(g['truth']) or 'no data'}")
    return out[:limit] + ([f"- … and {len(out) - limit} more"] if len(out) > limit else [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=["rules"])
    ap.add_argument("--cases", type=int, default=600, help="files per set (fit and held-out each)")
    args = ap.parse_args()

    doc = ["# Evaluation set and calibration (phase 9)\n",
           f"*Generated {dt.date.today()} by `scripts/calibrate.py`. Synthetic data only (C1).*\n",
           "Files are generated by `evalset/` from invented records: patients for `cdss_paciente` (clinical pack) "
           "as CSV, Excel, JSON, XML, HL7 v2 and FHIR, and order lines for `pedido_json` (no pack) as CSV, Excel, "
           "JSON and XML. Each file is messy in its own way (header languages and codes, section prefixes, title "
           "lines, encodings, separators, date shapes, sex codes, units, decimal commas, capitals, split or combined "
           "names, lost leading zeros, missing fields, distractor columns), and its correct output is known.\n",
           "A field is graded by its **output values**, not by its column name: the proposal is run on every row "
           "and compared with the correct values. **right**: every value right (or \"no data\" where the file has "
           "none). **pending**: left for a human. **missed**: \"no data\" where the file has it (incomplete, nothing "
           "false). **wrong**: some value wrong or invented; *silent* when the wrong value passes every rule of the "
           "destination (otherwise the engine sets those rows aside with the reason). **oracle**: the true columns "
           "with the transforms the rules choose for them, to tell column mistakes from transform mistakes.\n",
           "**Calibration**: for every field the proposal gave a column (mapped, or pending with a column), was "
           "accepting it as proposed right? Counted per score band on the *fit* set, made non-decreasing with the "
           "score, then checked on the *held-out* set. The expected calibration error (ECE) is the average gap "
           "between the calibrated rate and what happened on the held-out files.\n"]
    table_out = {}
    for model in args.models:
        fitted, s_fit, failed_fit = measure(model, args.cases, 1000)
        held, s_held, failed_held = measure(model, args.cases, 2000)
        if not fitted:
            doc += [f"## {model}\n", f"Not measured: the model did not answer ({failed_fit} files).\n"]
            continue
        table = fit(bands(points(fitted), EDGES))
        held_bands = bands(points(held), EDGES)
        ece = expected_error(table, points(held))
        raw_gap = _raw_gap(points(held))
        files = args.cases * 2 - failed_fit - failed_held
        doc += [f"## {model}\n",
                f"{files} files, {len(fitted) + len(held)} fields, {(s_fit + s_held) / max(files, 1):.2f} s per file.\n",
                "### Outcomes (fit + held-out)\n", *outcome_table(fitted + held), "",
                "### Confidence bands\n", *band_table(table, held_bands), "",
                f"Held-out ECE: **{ece:.1%}** with the calibrated rates, **{raw_gap:.1%}** reading the raw score as a "
                "probability.\n" if ece is not None else "Held-out ECE: not enough data.\n",
                "### Fields where accepting the proposal would be wrong\n", *(mistakes(fitted + held) or ["None."]), ""]
        table_out[model] = {"generated": str(dt.date.today()), "files": files,
                            "bands": [{"low": b["low"], "high": b["high"], "n": b["n"], "rate": b["calibrated"],
                                       "interval": b["interval"]} for b in table],
                            "held_out_ece": ece}
        print(f"{model}: {files} files, ECE {ece}", flush=True)
    doc += ["## Limits\n",
            "- The files are as messy as the generator makes them. Real exports will have problems it does not "
            "draw, so the rates are a ceiling measured on known kinds of mess, not a promise for a new hospital. "
            "The web app says \"en pruebas sintéticas\" next to them for that reason.",
            "- The matcher was fixed while building this set (seeds 0–299); the fit and held-out sets use other "
            "seeds, but the same generator, so they share its blind spots.",
            "- A band with few proposals has a wide interval; the web app shows how many proposals each rate rests on.",
            "- Only the bands are calibrated: the raw score still orders the review (recipe `confidence_kind`)."]
    (ROOT / "docs" / "CALIBRATION.md").write_text("\n".join(doc) + "\n", encoding="utf-8")
    path = ROOT / "multibridge" / "calibration.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    path.write_text(json.dumps({**old, **table_out}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote docs/CALIBRATION.md and multibridge/calibration.json")


def _raw_gap(pts: list[tuple[float, bool]]) -> float:
    """The calibration error of reading the score itself as a probability."""
    held = bands(pts, EDGES)
    total = sum(b["n"] for b in held) or 1
    return sum(abs(b["right"] - sum(c for c, _ in pts if b["low"] <= c < b["high"] or (b["high"] == 1.0 and c == 1.0)))
               for b in held) / total


if __name__ == "__main__":
    main()
