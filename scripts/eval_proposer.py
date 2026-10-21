"""Compare proposers against the reviewed golden plans and write docs/EVAL.md.

    .venv/Scripts/python scripts/eval_proposer.py                      # rules, qwen3:8b, qwen3:30b
    .venv/Scripts/python scripts/eval_proposer.py rules qwen3:8b       # just these

For each golden field the proposal is one of:
    right    same status and same columns as the reviewed plan
    pending  left for a human where the reviewed plan has an answer: costs review time, not safety
    wrong    a different column, or a column where the reviewed plan has none: a reviewer must catch it

Synthetic data only (COMPLIANCE C1). Models run locally through Ollama.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from multibridge import load  # noqa: E402
from multibridge.ai.ollama import OllamaUnavailable  # noqa: E402
from multibridge.expected import Expected  # noqa: E402
from multibridge.proposer import propose  # noqa: E402
from multibridge.records import to_rows  # noqa: E402

GOLDEN = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7"]
EXTRA = ["hospital_c_messy.xlsx", "hospital_a_diagnosticos.hl7", "hospital_b_condiciones.json"]


def grade(fields: dict, plan: dict) -> dict:
    out = {"right": [], "pending": [], "wrong": []}
    for target, g in plan.items():
        f = fields[target]
        if (f["status"], f["from"]) == (g["status"], g["from"]):
            out["right"].append(target)
        elif f["status"] == "pending":
            out["pending"].append(target)
        else:
            out["wrong"].append(f"{target}: {'+'.join(f['from']) or f['status']} (revisado: "
                                f"{'+'.join(g['from']) or g['status']})")
    return out


def main(models: list[str]) -> None:
    expected = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")
    lines = [f"# Proposer evaluation\n",
             f"*Generated {dt.date.today()} by `scripts/eval_proposer.py`. Synthetic data only.*\n",
             "Each golden field is **right** (same decision as the reviewed plan), **pending** "
             "(left for a human: costs time, not safety) or **wrong** (a reviewer must catch it).\n",
             "| proposer | file | right | pending | wrong | seconds |", "|---|---|---|---|---|---|"]
    details, extra = [], []
    for model in models:
        for name in GOLDEN + EXTRA:
            rows = to_rows(load(ROOT / "examples" / name))
            start = time.monotonic()
            try:
                draft = propose(rows, expected, model=model, second_pass=True)
            except OllamaUnavailable as e:
                lines.append(f"| {model} | {name} | error | | | {round(time.monotonic() - start, 1)} |")
                details.append(f"- **{model}, {name}**: not measured ({e})")
                print(f"{model:10} {name:30} ERROR {e}", flush=True)
                write(lines, details, extra)
                continue
            seconds = round(time.monotonic() - start, 1)
            if name in GOLDEN:
                plan = json.loads((ROOT / "tests" / "golden" / "plans" / f"{Path(name).stem}.json")
                                  .read_text(encoding="utf-8"))
                g = grade(draft["fields"], plan)
                lines.append(f"| {model} | {name} | {len(g['right'])}/{len(plan)} | {len(g['pending'])} | "
                             f"{len(g['wrong'])} | {seconds} |")
                if g["wrong"] or g["pending"]:
                    details.append(f"- **{model}, {name}**: "
                                   + "; ".join([f"wrong {w}" for w in g["wrong"]]
                                               + [f"pending {p}" for p in g["pending"]]))
            else:
                counts = {s: sum(f["status"] == s for f in draft["fields"].values())
                          for s in ("mapped", "no_data", "pending")}
                mapped = ", ".join(f"{t.split('.')[-1]}←{'+'.join(f['from'])}"
                                   for t, f in draft["fields"].items() if f["status"] == "mapped")
                extra.append(f"- **{model}, {name}** ({seconds} s): {counts['mapped']} mapped, "
                             f"{counts['no_data']} no data, {counts['pending']} pending. {mapped}")
            print(f"{model:10} {name:30} {seconds:6} s", flush=True)
            write(lines, details, extra)  # after every file: an interrupted run keeps what it measured
    print("wrote docs/EVAL.md")


def write(lines: list[str], details: list[str], extra: list[str]) -> None:
    out = lines + ["", "## Differences from the reviewed plans", ""] + (details or ["None."])
    out += ["", "## Files without a reviewed plan (no ground truth: check by hand)", ""] + extra
    (ROOT / "docs" / "EVAL.md").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or ["rules", "qwen3:8b", "qwen3:30b"])
