"""Run the hard synthetic files (examples/hard/) through the pipeline, without AI, and write docs/HARD_DATA.md.

    .venv/Scripts/python examples/hard/build_hard.py     # (re)generate the files + answers.json
    .venv/Scripts/python scripts/hard_data.py

Two separate questions per file:
  1. Proposer (rules): does it pick the right columns? Per destination field: right / pending / wrong.
     For a "gap" field (a correct recipe can't be expressed yet), pending is the right answer and
     mapped means the proposer confidently did something it can't do correctly.
  2. Pipeline (parsers + records + engine): given the CORRECT recipe from answers.json, are the
     output records exactly right, and are the right rows set aside? Gap fields are left empty here.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from multibridge import load  # noqa: E402
from multibridge.engine import run  # noqa: E402
from multibridge.expected import Expected  # noqa: E402
from multibridge.matcher import propose  # noqa: E402
from multibridge.recipe import approve, new  # noqa: E402
from multibridge.records import to_rows  # noqa: E402

HARD = ROOT / "examples" / "hard"


def expected_for(gaps: set[str]) -> Expected:
    """The real destination, except that gap fields can't be required (no correct recipe exists for them yet)."""
    example = json.loads((ROOT / "expected" / "cdss_paciente.example.json").read_text(encoding="utf-8"))
    rules = json.loads((ROOT / "expected" / "cdss_paciente.rules.json").read_text(encoding="utf-8"))
    for g in gaps:
        rules.setdefault(g, {})["required"] = False
    return Expected.from_example(example, name="cdss_paciente", rules=rules)


def grade_proposer(draft: dict, plan: dict) -> tuple[dict, list[str]]:
    counts = {"right": 0, "pending": 0, "wrong": 0}
    notes = []
    for target, truth in plan.items():
        f = draft["fields"][target]
        got = "+".join(f["from"]) or f["status"]
        if truth["status"] == "gap":
            if f["status"] == "pending":
                counts["right"] += 1
            elif f["status"] == "mapped":
                counts["wrong"] += 1
                notes.append(f"wrong `{target}` ← {got}: needs a feature ({truth['why']})")
            else:
                counts["pending"] += 1
                notes.append(f"silent `{target}`: says no data, but the data is there ({truth['why']})")
        elif (f["status"], f["from"]) == (truth["status"], truth["from"]):
            counts["right"] += 1
            if f["transforms"] != truth["transforms"]:
                notes.append(f"right column, different transforms `{target}`: {f['transforms']} vs {truth['transforms']}")
        elif f["status"] == "pending":
            counts["pending"] += 1
            notes.append(f"pending `{target}` (correct: {'+'.join(truth['from']) or 'no_data'})")
        else:
            counts["wrong"] += 1
            notes.append(f"wrong `{target}` ← {got} (correct: {'+'.join(truth['from']) or 'no_data'})")
    return counts, notes


def check_pipeline(rows, answer: dict) -> tuple[str, list[str]]:
    plan = answer["plan"]
    gaps = {t for t, p in plan.items() if p["status"] == "gap"}
    expected = expected_for(gaps)
    fields = {t: (p if p["status"] != "gap" else {"status": "no_data", "from": [], "transforms": []})
              for t, p in plan.items()}
    fields = {t: {**f, "confidence": None, "why": [], "issues": []} for t, f in fields.items()}
    missing = [c for f in fields.values() for c in f["from"] if c not in rows.columns]
    if missing:
        return "columns missing", [f"the parser didn't produce columns {missing}"]
    result = run(rows, approve(new("hard", rows, expected, fields, proposed_by="answers"), expected, by="test"), expected)
    problems = []
    for i, (got, want) in enumerate(zip(result.records, answer["records"])):
        for section, values in want.items():
            for k, v in values.items():
                g = got.get(section, {}).get(k)
                if g != v:
                    problems.append(f"record {i} `{section}.{k}`: got {g!r}, expected {v!r}")
    if len(result.records) != len(answer["records"]):
        problems.append(f"{len(result.records)} records accepted, expected {len(answer['records'])}")
    got_rej = {(e["row"], e["field"]) for e in result.report["errors"]}
    want_rej = {(r["row"], r["field"]) for r in answer["rejected"]}
    if got_rej != want_rej:
        problems.append(f"rejected rows {sorted(got_rej)}, expected {sorted(want_rej)}")
    return ("ok" if not problems else f"{len(problems)} problem(s)"), problems


def main() -> None:
    answers = json.loads((HARD / "answers.json").read_text(encoding="utf-8"))
    expected = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")
    table = ["| file | proposer (rules): right / pending / wrong | pipeline with the correct recipe |",
             "|---|---|---|"]
    sections = []
    for name, answer in answers.items():
        out = [f"### {name}", ""]
        try:
            rows = to_rows(load(HARD / name))
        except Exception as e:  # a parser crash is itself a finding
            table.append(f"| {name} | parser crashed | parser crashed |")
            sections += out + [f"- **Parser crashed:** `{type(e).__name__}: {e}`", "", "```",
                               traceback.format_exc(limit=3), "```", ""]
            continue
        counts, notes = grade_proposer(propose(rows, expected), answer["plan"])
        try:
            status, problems = check_pipeline(rows, answer)
        except Exception as e:
            status, problems = "crashed", [f"`{type(e).__name__}: {e}`"]
        table.append(f"| {name} | {counts['right']} / {counts['pending']} / {counts['wrong']} | {status} |")
        out += ["**Proposer (rules)**", ""] + [f"- {n}" for n in notes or ["all 15 fields right"]]
        out += ["", "**Pipeline**", ""] + [f"- {p}" for p in problems or ["output identical to the expected records"]]
        sections += out + [""]
        print(f"{name:28} proposer {counts}  pipeline {status}", flush=True)
    gaps = sorted({f"- `{t}`: {p['why']}" for a in answers.values() for t, p in a["plan"].items()
                   if p["status"] == "gap"})
    doc = ["# Hard data test (no AI)", "",
           "*Generated by `scripts/hard_data.py` from `examples/hard/` (synthetic data only). "
           "Every file renders the same three invented patients, so the correct answer is known.*", "",
           *table, "", "## Feature gaps the files expose (correct recipe not expressible yet)", "", *gaps, "",
           "## Details", "", *sections]
    (ROOT / "docs" / "HARD_DATA.md").write_text("\n".join(doc) + "\n", encoding="utf-8")
    print("wrote docs/HARD_DATA.md")


if __name__ == "__main__":
    main()
