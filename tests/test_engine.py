import copy
from pathlib import Path

import pytest

from multibridge import load
from multibridge.contract import Contract, TargetField, from_example
from multibridge.driver import ApprovalError, approve, compatible, problems, verify
from multibridge.engine import _title, apply_value_op, run
from multibridge.matcher import propose
from multibridge.parsers import parse_bytes

ROOT = Path(__file__).parent.parent
CONTRACT = Contract.load(ROOT / "contracts" / "cdss_paciente.v1.json")


@pytest.mark.parametrize("op, value, expected", [
    ({"op": "date", "from": "%d/%m/%Y"}, "5/1/1958", "1958-01-05"),
    ({"op": "date", "from": "%Y%m%d"}, "20260310100700", "2026-03-10"),
    ({"op": "number", "decimal": ","}, "1.234,5", 1234.5),
    ({"op": "number"}, "168", 168),
    ({"op": "phone", "country": "34"}, "600 77 78 88", "+34600777888"),
    ({"op": "phone", "country": "34"}, "0034600777888", "+34600777888"),
    ({"op": "pad", "width": 5}, "3001", "03001"),
    ({"op": "map", "values": {"0+": "O+"}}, "A-", "A-"),
    ({"op": "scale", "factor": 0.001}, "70500", 70.5),
])
def test_value_ops(op, value, expected):
    assert apply_value_op(op, value) == expected


def test_title_case_keeps_spanish_connectors_and_hyphens():
    assert _title("FERNANDEZ-VALLINA DE LA TORRE") == "Fernandez-Vallina de la Torre"


def _plan(name="hospital_alvarez_buylla.csv"):
    ds = load(ROOT / "examples" / name)
    return ds, propose(ds, CONTRACT)


def test_drafts_cannot_run():
    ds, plan = _plan()
    with pytest.raises(ApprovalError):
        run(ds, plan, CONTRACT)


def test_editing_an_approved_driver_invalidates_the_approval():
    ds, plan = _plan()
    approved = approve(plan, CONTRACT, by="Ana")
    verify(approved)
    tampered = copy.deepcopy(approved)
    tampered["mappings"][0]["sources"][0]["path"] = "DNI"
    with pytest.raises(ApprovalError, match="modificó"):
        run(ds, tampered, CONTRACT)


def test_required_field_without_source_blocks_approval():
    raw = "Nombre;Apellidos;Sexo\nAna;Pérez;M\n".encode("utf-8")
    ds = parse_bytes(raw, "minimo.csv")
    plan = propose(ds, CONTRACT)
    blockers = problems(plan, CONTRACT)
    assert any("paciente.id" in b for b in blockers)
    assert any("paciente.fecha_nacimiento" in b for b in blockers)
    with pytest.raises(ApprovalError):
        approve(plan, CONTRACT, by="Ana")


def test_ambiguous_sex_code_is_left_for_a_human():
    """'M' alone: mujer (Spanish H/M) or male (English M/F)? Rules must not guess."""
    raw = "NHC;Nombre;Apellidos;F. Nacimiento;Sexo\nX1;Ana;Pérez;01/01/1980;M\nX2;Eva;Gil;02/02/1990;M\n".encode()
    plan = propose(parse_bytes(raw, "solo_m.csv"), CONTRACT)
    sexo = next(m for m in plan["mappings"] if m["target"] == "paciente.sexo")
    assert sexo["status"] == "pending"
    assert "M" in sexo["issues"][0]


def test_bad_records_are_separated_not_fixed():
    raw = ("NHC;Nombre;Apellidos;F. Nacimiento;Sexo;Grupo sanguíneo\n"
           "X1;Ana;Pérez;01/01/1980;H;A+\n"
           "X2;Eva;Gil;31/02/1990;M;A+\n"          # impossible date
           "X3;Luz;Ríos;03/03/1970;M;Z+\n").encode()  # not a blood group
    ds = parse_bytes(raw, "errores.csv")
    plan = propose(ds, CONTRACT)
    grupo = next(m for m in plan["mappings"] if m["target"] == "datos_clinicos.grupo_sanguineo")
    grupo["status"] = "mapped"  # reviewer accepts the column; bad values must still be caught at run time
    result = run(ds, approve(plan, CONTRACT, by="Ana"), CONTRACT)
    assert len(result.records) == 1
    reasons = {(e["record"], e["target"]) for e in result.report["errors"]}
    assert reasons == {(1, "paciente.fecha_nacimiento"), (2, "datos_clinicos.grupo_sanguineo")}
    assert "Gil" not in str(result.report) and "Z+" not in str(result.report)  # no data values in the report


def test_driver_reuse_requires_the_same_structure():
    ds, plan = _plan()
    approved = approve(plan, CONTRACT, by="Ana")
    assert compatible(approved, ds, CONTRACT) == []
    other = load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7")
    assert compatible(approved, other, CONTRACT)


def test_contract_from_example_drafts_types_and_concepts():
    import json
    example = json.loads((ROOT / "examples" / "destino_expected.json").read_text(encoding="utf-8"))
    c = from_example(example, name="borrador")
    by_path = {f.path: f for f in c.fields}
    assert by_path["paciente.fecha_nacimiento"].type == "date"
    assert by_path["datos_clinicos.peso_kg"].type == "number"
    assert by_path["datos_clinicos.altura_cm"].type == "integer"
    assert by_path["paciente.sexo"].concept == "sexo"
    assert by_path["datos_clinicos.grupo_sanguineo"].concept == "grupo_sanguineo"


def test_contract_rejects_unknown_types():
    with pytest.raises(ValueError):
        TargetField(path="x", type="datetime")
