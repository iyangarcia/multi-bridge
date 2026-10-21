import copy
import json
from pathlib import Path

import pytest

from multibridge import load
from multibridge.engine import VALUE_TRANSFORMS, _title, run
from multibridge.expected import Expected, Target
from multibridge.matcher import propose
from multibridge.parsers import parse_bytes
from multibridge.recipe import ApprovalError, approve, compatible, problems, verify
from multibridge.records import to_rows

ROOT = Path(__file__).parent.parent
EXPECTED = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")


def rows_of(raw: bytes, name: str):
    return to_rows(parse_bytes(raw, name))


@pytest.mark.parametrize("op, value, expected", [
    ({"op": "date", "from": "%d/%m/%Y"}, "5/1/1958", "1958-01-05"),
    ({"op": "date", "from": "%Y%m%d"}, "20260310100700", "2026-03-10"),
    ({"op": "number", "decimal": ","}, "1.234,5", 1234.5),
    ({"op": "number"}, "168", 168),
    ({"op": "phone", "country": "34"}, "600 77 78 88", "+34600777888"),
    ({"op": "phone", "country": "34"}, "0034600777888", "+34600777888"),
    ({"op": "pad", "width": 5}, "3001", "03001"),
    ({"op": "translate", "values": {"0+": "O+"}}, "A-", "A-"),
    ({"op": "scale", "factor": 0.001}, "70500", 70.5),
    ({"op": "split", "sep": " ", "index": -1}, "Ana Pérez Gil", "Gil"),
])
def test_value_transforms(op, value, expected):
    assert VALUE_TRANSFORMS[op["op"]](value, op) == expected


def test_title_case_keeps_spanish_connectors_and_hyphens():
    assert _title("FERNANDEZ-VALLINA DE LA TORRE") == "Fernandez-Vallina de la Torre"


def _draft(name="hospital_alvarez_buylla.csv"):
    rows = to_rows(load(ROOT / "examples" / name))
    return rows, propose(rows, EXPECTED)


def test_drafts_cannot_run():
    rows, draft = _draft()
    with pytest.raises(ApprovalError):
        run(rows, draft, EXPECTED)


def test_editing_an_approved_recipe_invalidates_it():
    rows, draft = _draft()
    approved = approve(draft, EXPECTED, by="Ana")
    verify(approved)
    tampered = copy.deepcopy(approved)
    tampered["fields"]["paciente.id"]["from"] = ["DNI"]
    with pytest.raises(ApprovalError, match="modificó"):
        run(rows, tampered, EXPECTED)


def test_approval_records_what_the_human_changed():
    rows, draft = _draft()
    draft["fields"]["datos_clinicos.alergia"] = {**draft["fields"]["datos_clinicos.alergia"],
                                                 "status": "no_data", "from": [], "transforms": []}
    approved = approve(draft, EXPECTED, by="Ana")
    assert approved["fields"]["datos_clinicos.alergia"]["changed_by"] == "Ana"
    assert "changed_by" not in approved["fields"]["paciente.id"]
    assert approved["fields"]["paciente.id"]["proposed_by"] == "rules"


def test_required_field_without_source_blocks_approval():
    rows = rows_of("Nombre;Apellidos;Sexo\nAna;Pérez;H\n".encode(), "minimo.csv")
    draft = propose(rows, EXPECTED)
    blockers = problems(draft, EXPECTED)
    assert any("paciente.id" in b for b in blockers)
    assert any("paciente.fecha_nacimiento" in b for b in blockers)
    with pytest.raises(ApprovalError):
        approve(draft, EXPECTED, by="Ana")


def test_ambiguous_sex_code_is_left_for_a_human():
    """'M' alone: mujer (Spanish H/M) or male (English M/F)? Rules must not guess."""
    rows = rows_of("NHC;Nombre;Apellidos;F. Nacimiento;Sexo\nX1;Ana;Pérez;01/01/1980;M\nX2;Eva;Gil;02/02/1990;M\n"
                   .encode(), "solo_m.csv")
    sexo = propose(rows, EXPECTED)["fields"]["paciente.sexo"]
    assert sexo["status"] == "pending" and "M" in sexo["issues"][0]


def test_bad_rows_are_set_aside_not_fixed():
    rows = rows_of(("NHC;Nombre;Apellidos;F. Nacimiento;Sexo;Grupo sanguíneo\n"
                    "X1;Ana;Pérez;01/01/1980;H;A+\n"
                    "X2;Eva;Gil;31/02/1990;M;A+\n"          # impossible date
                    "X3;Luz;Ríos;03/03/1970;M;Z+\n").encode(), "errores.csv")  # not a blood group
    draft = propose(rows, EXPECTED)
    draft["fields"]["datos_clinicos.grupo_sanguineo"]["status"] = "mapped"  # reviewer accepts the column
    result = run(rows, approve(draft, EXPECTED, by="Ana"), EXPECTED)
    assert len(result.records) == 1
    assert {(e["row"], e["field"]) for e in result.report["errors"]} == {
        (1, "paciente.fecha_nacimiento"), (2, "datos_clinicos.grupo_sanguineo")}
    assert "Gil" not in str(result.report) and "Z+" not in str(result.report)  # no data values in the report


def test_several_values_without_a_rule_are_an_error():
    t = Target(path="x.y")
    from multibridge.engine import TransformError, field_value
    with pytest.raises(TransformError):
        field_value({"A": ["1", "2"]}, {"from": ["A"], "transforms": []}, t)
    t.multiple = "join"
    assert field_value({"A": ["1", "2"]}, {"from": ["A"], "transforms": []}, t) == "1; 2"


def test_recipe_reuse_requires_the_same_structure():
    rows, draft = _draft()
    approved = approve(draft, EXPECTED, by="Ana")
    assert compatible(approved, rows, EXPECTED) == []
    assert compatible(approved, to_rows(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7")), EXPECTED)


def test_changing_the_destination_invalidates_old_recipes():
    rows, draft = _draft()
    approved = approve(draft, EXPECTED, by="Ana")
    example = json.loads((ROOT / "expected" / "cdss_paciente.example.json").read_text(encoding="utf-8"))
    rules = json.loads((ROOT / "expected" / "cdss_paciente.rules.json").read_text(encoding="utf-8"))
    rules["paciente.dni"]["required"] = True
    stricter = Expected.from_example(example, name="cdss_paciente", rules=rules)
    assert stricter.id != EXPECTED.id
    assert compatible(approved, rows, stricter)


def test_expected_is_read_from_the_example():
    by_path = {t.path: t for t in EXPECTED.targets}
    assert len(by_path) == 15
    assert by_path["paciente.fecha_nacimiento"].type == "date"
    assert by_path["datos_clinicos.peso_kg"].type == "number"
    assert by_path["direccion.ciudad"].concept == "ciudad"          # the leaf decides, not "direccion"
    assert by_path["datos_clinicos.altura_cm"].type == "number"     # overlay widens the example's integer
    assert by_path["paciente.sexo"].enum == ["male", "female", "other", "unknown"]


def test_rules_overlay_cannot_invent_fields():
    with pytest.raises(ValueError, match="no está en el ejemplo"):
        Expected.from_example({"a": 1}, name="x", rules={"b": {"required": True}})
