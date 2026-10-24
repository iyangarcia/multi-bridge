"""Measure the two first translations (ROADMAP phases 7 and 8) and write docs/TRANSLATIONS.md.

    .venv/Scripts/python scripts/translations.py                 # rules only
    .venv/Scripts/python scripts/translations.py rules qwen3:8b  # and the local model (Ollama must run)

    A. messy Excel -> FHIR Bundle (clinical pack); truth: tests/golden/fhir/*.plan.json
    B. CSV order lines -> nested JSON and XML (no pack); truth: examples/pedidos/answers.json

Per destination field the proposal is right (same status and columns as the truth), pending (left
for a human: costs time, not safety) or wrong (a different column, or "no data" where the data is
there: a reviewer must catch it). Wrong must stay at 0. Then the reviewed recipe is run and its
output written and checked in the destination's format. Synthetic data only (COMPLIANCE C1).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from multibridge import formats, load  # noqa: E402
from multibridge.ai.ollama import OllamaUnavailable  # noqa: E402
from multibridge.engine import run  # noqa: E402
from multibridge.expected import Expected  # noqa: E402
from multibridge.proposer import propose  # noqa: E402
from multibridge.recipe import approve  # noqa: E402
from multibridge.records import to_rows  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "fhir"
BUNDLE = ROOT / "expected" / "paciente_resumen_fhir.example.json"
ORDERS = ROOT / "examples" / "pedidos"


def cases() -> list[tuple[str, Path, Path, dict, list[str]]]:
    """(label, source, destination, true plan, columns the reviewer carries)."""
    out = []
    for name, carry in (("hospital_c_messy.xlsx", ["Clínica / Campo libre 1"]),
                        ("hard/h5_excel_dificil.xlsx", ["Clínica / Grupo sanguíneo"])):
        plan = json.loads((GOLDEN / f"{Path(name).stem}.plan.json").read_text(encoding="utf-8"))["fields"]
        out.append(("A · Excel → FHIR", ROOT / "examples" / name, BUNDLE, plan, carry))
    answers = json.loads((ORDERS / "answers.json").read_text(encoding="utf-8"))["pedidos_lineas.csv"]
    for dest, path in (("pedido_json", "pedido_json.example.json"), ("pedido_xml", "pedido_xml.example.xml")):
        out.append((f"B · CSV → {dest.split('_')[1].upper()}", ORDERS / "pedidos_lineas.csv",
                    ROOT / "examples" / "destinos" / path, answers[dest]["plan"], ["Comercial"]))
    return out


def grade(fields: dict, plan: dict) -> dict:
    out = {"right": [], "pending": [], "wrong": []}
    for target, truth in plan.items():
        f = fields[target]
        if f["status"] == "pending":
            out["pending"].append(target)
        elif (f["status"], f["from"]) == (truth["status"], truth["from"]):
            out["right"].append(target)
        else:
            out["wrong"].append(f"{target}: {'+'.join(f['from']) or f['status']} "
                                f"(correcto: {'+'.join(truth['from']) or truth['status']})")
    return out


def main(models: list[str]) -> None:
    lines = ["# The two first translations (phases 7 and 8)\n",
             f"*Generated {dt.date.today()} by `scripts/translations.py`. Synthetic data only.*\n",
             "Per destination field: **right** (the reviewed decision), **pending** (left for a human: costs "
             "time, not safety) or **wrong** (a reviewer must catch it; must stay 0). *Output* is the reviewed "
             "recipe run, written in the destination's format and checked by its checker.\n",
             "A's truth is the reviewed golden plan, drafted by the rules and checked by hand, so the rules' "
             "score there guards against regressions rather than measuring them independently; B's truth "
             "(`examples/pedidos/answers.json`) was written before any proposal.\n",
             "| translation | proposer | source | right | pending | wrong | output | seconds |",
             "|---|---|---|---|---|---|---|---|"]
    details = []
    for model in models:
        for label, source, dest, plan, carry in cases():
            expected = Expected.load(dest)
            rows = to_rows(load(source))
            start = time.monotonic()
            try:
                draft = propose(rows, expected, model=model)
            except OllamaUnavailable as e:
                lines.append(f"| {label} | {model} | {source.name} | error | | | | |")
                details.append(f"- **{model}, {source.name} → {dest.name}**: not measured ({e})")
                continue
            seconds = round(time.monotonic() - start, 1)
            g = grade(draft["fields"], plan)
            reviewed = json.loads(json.dumps(draft))
            for t, f in reviewed["fields"].items():   # the reviewer applies the true plan
                f.update(status=plan[t]["status"], **{"from": plan[t]["from"], "transforms": plan[t]["transforms"]})
            used = {c for f in reviewed["fields"].values() for c in f["from"]}   # unused columns after review
            reviewed["unmatched"] = [c for c, f in rows.columns.items() if c not in used and f.dtype != "empty"]
            result = run(rows, approve(reviewed, expected, by="eval", carry=carry), expected)
            problems = formats.get(expected.format).check(result.write(expected))
            output = (f"{len(result.items)} items, {len(result.rejected)} set aside, "
                      + ("check passed" if not problems else f"{len(problems)} problems"))
            lines.append(f"| {label} | {model} | {source.name} → {dest.name} | {len(g['right'])}/{len(plan)} | "
                         f"{len(g['pending'])} | {len(g['wrong'])} | {output} | {seconds} |")
            if g["wrong"] or g["pending"]:
                details.append(f"- **{model}, {source.name} → {dest.name}**: "
                               + "; ".join([f"wrong {w}" for w in g["wrong"]] + [f"pending `{p}`" for p in g["pending"]]))
            print(f"{model:10} {source.name:24} {dest.name:34} {len(g['right'])}/{len(plan)} "
                  f"wrong={len(g['wrong'])}", flush=True)
    out = lines + ["", "## Fields not right on the first proposal", ""] + (details or ["None."])
    (ROOT / "docs" / "TRANSLATIONS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote docs/TRANSLATIONS.md")


if __name__ == "__main__":
    main(sys.argv[1:] or ["rules"])
