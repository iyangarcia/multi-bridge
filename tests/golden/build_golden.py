"""Regenerate the golden files from the current pipeline.

    python tests/golden/build_golden.py

Golden files are the reviewed truth. Only regenerate after a deliberate change,
and read the diff record by record before keeping it: a golden file that just
mirrors the code proves nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from multibridge import load
from multibridge.engine import run
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.recipe import approve
from multibridge.records import to_rows

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HOSPITALS = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7"]


def reduced(recipe: dict) -> dict:
    """The decisions a reviewer checks: no confidences, timestamps or explanations."""
    return {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]}
            for t, f in recipe["fields"].items()}


def main() -> None:
    expected = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")
    for name in HOSPITALS:
        rows = to_rows(load(ROOT / "examples" / name))
        draft = propose(rows, expected)
        result = run(rows, approve(draft, expected, by="golden"), expected)
        stem = Path(name).stem
        for folder, content in (("plans", reduced(draft)), ("output", result.records)):
            p = HERE / folder / f"{stem}.json"
            p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {len(result.records)} records, {len(result.rejected)} rejected")


if __name__ == "__main__":
    main()
