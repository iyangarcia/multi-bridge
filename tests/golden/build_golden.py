"""Regenerate the golden files from the current matcher + engine.

    python tests/golden/build_golden.py

Golden files are the reviewed truth. Only regenerate after a deliberate change,
and read the diff record by record before keeping it: a golden file that just
mirrors the code proves nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from multibridge import load
from multibridge.contract import Contract
from multibridge.driver import approve
from multibridge.engine import run
from multibridge.matcher import propose

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HOSPITALS = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7"]


def reduced_plan(driver: dict) -> dict:
    """The decisions a reviewer cares about, without scores, timestamps or explanations."""
    return {
        "root": driver["source"]["root"],
        "join": driver["source"]["join"],
        "mappings": {m["target"]: {"status": m["status"],
                                   "sources": [f"{s['entity']}:{s['path']}" for s in m["sources"]],
                                   "ops": m["ops"]} for m in driver["mappings"]},
    }


def main() -> None:
    contract = Contract.load(ROOT / "contracts" / "cdss_paciente.v1.json")
    for name in HOSPITALS:
        ds = load(ROOT / "examples" / name)
        plan = propose(ds, contract)
        result = run(ds, approve(plan, contract, by="golden"), contract)
        stem = Path(name).stem
        for folder, content in (("plans", reduced_plan(plan)), ("output", result.records)):
            p = HERE / folder / f"{stem}.json"
            p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {len(result.records)} records, {len(result.rejected)} rejected")


if __name__ == "__main__":
    main()
