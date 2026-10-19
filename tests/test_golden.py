"""The core claim: three hospitals, three formats, one contract, zero per-hospital code.

For each hospital the matcher's proposal must equal the reviewed plan, and the
approved plan must produce exactly the reviewed output.
"""

import json
from pathlib import Path

import pytest

from multibridge import load
from multibridge.contract import Contract
from multibridge.driver import approve
from multibridge.engine import run
from multibridge.matcher import propose

GOLDEN = Path(__file__).parent / "golden"
ROOT = Path(__file__).parent.parent
HOSPITALS = {
    "hospital_alvarez_buylla.csv": "csv",     # Hospital C: Excel/CSV export
    "hospital_leon_fhir.json": "fhir",        # Hospital B: FHIR API
    "huca_oviedo_hl7v23.hl7": "hl7v2",        # Hospital A: HL7 v2.3 messages
}


def reduced_plan(driver):
    return {
        "root": driver["source"]["root"],
        "join": driver["source"]["join"],
        "mappings": {m["target"]: {"status": m["status"],
                                   "sources": [f"{s['entity']}:{s['path']}" for s in m["sources"]],
                                   "ops": m["ops"]} for m in driver["mappings"]},
    }


@pytest.fixture(scope="module")
def contract():
    return Contract.load(ROOT / "contracts" / "cdss_paciente.v1.json")


def _golden(kind, name):
    return json.loads((GOLDEN / kind / f"{Path(name).stem}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name, fmt", HOSPITALS.items())
def test_matcher_proposes_the_reviewed_plan(name, fmt, contract):
    ds = load(ROOT / "examples" / name)
    assert ds.format == fmt
    assert reduced_plan(propose(ds, contract)) == _golden("plans", name)


@pytest.mark.parametrize("name", HOSPITALS)
def test_approved_plan_produces_the_reviewed_output(name, contract):
    ds = load(ROOT / "examples" / name)
    result = run(ds, approve(propose(ds, contract), contract, by="test"), contract)
    assert result.rejected == []
    assert result.records == _golden("output", name)


def test_all_three_hospitals_deliver_the_same_shape(contract):
    shapes = set()
    for name in HOSPITALS:
        for rec in _golden("output", name):
            shapes.add(json.dumps({k: sorted(v) for k, v in rec.items()}, sort_keys=True))
            for t in contract.fields:
                section, leaf = t.path.split(".")
                assert contract.check(t, rec[section][leaf]) is None, (name, t.path)
    assert len(shapes) == 1


def test_missing_data_stays_missing(contract):
    """León's FHIR has no postal code and no doctor: null, never invented."""
    for rec in _golden("output", "hospital_leon_fhir.json"):
        assert rec["direccion"]["codigo_postal"] is None
        assert rec["datos_clinicos"]["medico_responsable"] is None


def test_same_patient_style_as_the_example_destination():
    """HUCA sends 'MARTINEZ^PABLO'; destino_expected.json shows 'Pablo Martinez'."""
    expected = json.loads((ROOT / "examples" / "destino_expected.json").read_text(encoding="utf-8"))
    huca = _golden("output", "huca_oviedo_hl7v23.json")
    assert expected["datos_clinicos"]["medico_responsable"] == "Pablo Martinez"
    assert huca[0]["datos_clinicos"]["medico_responsable"] == "Pablo Martinez"
    assert set(huca[0]) == set(expected)
