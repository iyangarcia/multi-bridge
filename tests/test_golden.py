"""The core claim: three hospitals, three formats, one example of the destination, zero per-hospital code.

For each hospital the proposal must equal the reviewed plan, and the approved recipe
must produce exactly the reviewed output.
"""

import json
from pathlib import Path

import pytest

from multibridge import load
from multibridge.engine import run
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.recipe import approve
from multibridge.records import to_rows

GOLDEN = Path(__file__).parent / "golden"
ROOT = Path(__file__).parent.parent
HOSPITALS = {
    "hospital_alvarez_buylla.csv": "csv",     # Hospital C: Excel/CSV export
    "hospital_leon_fhir.json": "fhir",        # Hospital B: FHIR API
    "huca_oviedo_hl7v23.hl7": "hl7v2",        # Hospital A: HL7 v2.3 messages
}


@pytest.fixture(scope="module")
def expected():
    return Expected.load(ROOT / "expected" / "cdss_paciente.example.json")


def _golden(kind, name):
    return json.loads((GOLDEN / kind / f"{Path(name).stem}.json").read_text(encoding="utf-8"))


def _reduced(recipe):
    return {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]}
            for t, f in recipe["fields"].items()}


@pytest.mark.parametrize("name, fmt", HOSPITALS.items())
def test_proposal_is_the_reviewed_plan(name, fmt, expected):
    rows = to_rows(load(ROOT / "examples" / name))
    assert rows.format == fmt
    assert _reduced(propose(rows, expected)) == _golden("plans", name)


@pytest.mark.parametrize("name", HOSPITALS)
def test_approved_recipe_produces_the_reviewed_output(name, expected):
    rows = to_rows(load(ROOT / "examples" / name))
    result = run(rows, approve(propose(rows, expected), expected, by="test"), expected)
    assert result.rejected == []
    assert result.records == _golden("output", name)


def test_all_three_hospitals_deliver_the_same_shape(expected):
    shapes = set()
    for name in HOSPITALS:
        for rec in _golden("output", name):
            shapes.add(json.dumps({k: sorted(v) for k, v in rec.items()}, sort_keys=True))
            for t in expected.targets:
                section, leaf = t.path.split(".")
                assert Expected.check(t, rec[section][leaf]) is None, (name, t.path)
    assert len(shapes) == 1


def test_missing_data_stays_missing():
    """León's FHIR has no postal code and no doctor: null, never invented."""
    for rec in _golden("output", "hospital_leon_fhir.json"):
        assert rec["direccion"]["codigo_postal"] is None
        assert rec["datos_clinicos"]["medico_responsable"] is None


def test_output_looks_like_the_example(expected):
    """HUCA sends 'MARTINEZ^PABLO'; the example destination shows 'Pablo Martinez'."""
    example = json.loads((ROOT / "expected" / "cdss_paciente.example.json").read_text(encoding="utf-8"))
    huca = _golden("output", "huca_oviedo_hl7v23.json")
    assert example["datos_clinicos"]["medico_responsable"] == "Pablo Martinez"
    assert huca[0]["datos_clinicos"]["medico_responsable"] == "Pablo Martinez"
    assert set(huca[0]) == set(example)
