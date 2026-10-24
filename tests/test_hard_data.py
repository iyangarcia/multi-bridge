"""Hard synthetic files (examples/hard/): the correct answers are known because every file renders the
same three invented patients. Regenerate with `python examples/hard/build_hard.py`.
"""

import json
from pathlib import Path

import pytest

from multibridge import load
from multibridge.engine import run
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.recipe import approve, new
from multibridge.records import to_rows

ROOT = Path(__file__).parent.parent
HARD = ROOT / "examples" / "hard"
ANSWERS = json.loads((HARD / "answers.json").read_text(encoding="utf-8"))
EXPECTED = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")


def rows_of(name):
    return to_rows(load(HARD / name))


def fields_of(name):
    return propose(rows_of(name), EXPECTED)["fields"]


def expected_without(gaps):
    example = json.loads((ROOT / "expected" / "cdss_paciente.example.json").read_text(encoding="utf-8"))
    rules = json.loads((ROOT / "expected" / "cdss_paciente.rules.json").read_text(encoding="utf-8"))
    for g in gaps:
        rules.setdefault(g, {})["required"] = False
    return Expected.from_example(example, name="cdss_paciente", rules=rules)


@pytest.mark.parametrize("name", ANSWERS)
def test_pipeline_with_the_correct_recipe_gives_exactly_the_right_records(name):
    answer, rows = ANSWERS[name], rows_of(name)
    gaps = {t for t, p in answer["plan"].items() if p["status"] == "gap"}
    expected = expected_without(gaps)
    fields = {t: {**(p if p["status"] != "gap" else {"status": "no_data", "from": [], "transforms": []}),
                  "confidence": None, "why": [], "issues": []} for t, p in answer["plan"].items()}
    result = run(rows, approve(new("hard", rows, expected, fields, proposed_by="answers"), expected, by="t"), expected)
    assert result.records == answer["records"]
    assert {(e["row"], e["field"]) for e in result.report["errors"]} == {
        (r["row"], r["field"]) for r in answer["rejected"]}


@pytest.mark.parametrize("name", ANSWERS)
def test_rules_never_map_a_field_that_needs_a_missing_feature(name):
    """Gap fields (no correct recipe possible yet) must reach a human as pending, never be mapped."""
    fields = fields_of(name)
    for target, truth in ANSWERS[name]["plan"].items():
        if truth["status"] == "gap":
            assert fields[target]["status"] == "pending", (target, fields[target])


@pytest.mark.parametrize("name", ANSWERS)
def test_rules_mapped_fields_use_the_right_columns(name):
    """Whatever the rules do map must be right: a miss is acceptable, a wrong column is not."""
    fields = fields_of(name)
    for target, truth in ANSWERS[name]["plan"].items():
        f = fields[target]
        if f["status"] == "mapped" and truth["status"] != "gap":
            assert f["from"] == truth["from"], (target, f["from"], truth["from"])


def test_two_identifiers_in_one_hl7_field_are_picked_by_type():
    """PID-3 = DNI~NHC (or NHC~DNI): the first repetition is never assumed; PID-3.5 decides."""
    fields = fields_of("h3_hl7_v25.hl7")
    assert fields["paciente.id"]["from"] == ["PID-3.1 [PID-3.5=MR]"] and fields["paciente.id"]["status"] == "mapped"
    assert fields["paciente.dni"]["from"] == ["PID-3.1 [PID-3.5=NI]"]


def test_selector_columns_stay_aligned_per_repetition():
    rows = rows_of("h3_hl7_v25.hl7")
    assert rows.values("PID-3.1 [PID-3.5=MR]") == ["NHC-30001", "NHC-30002", "NHC-30003"]
    assert rows.values("PID-3.1 [PID-3.5=NI]") == ["12345678Z", None, "53123456T"]   # message 2 has no DNI
    assert "PID-3.4 [PID-3.5=MR]" not in rows.columns     # metadata components get no selector


def test_a_room_number_is_not_a_height():
    altura = fields_of("h3_hl7_v25.hl7")["datos_clinicos.altura_cm"]
    assert altura["from"] == ["ZBG-4"]                       # not PV1-3.2 (habitación 101, 202)


def test_hl7_second_given_name_and_mixed_timestamp_precision():
    fields = fields_of("h3_hl7_v25.hl7")
    assert fields["paciente.nombre"]["from"] == ["PID-5.2", "PID-5.3"]
    assert fields["paciente.fecha_nacimiento"]["transforms"] == [{"op": "date", "from": "%Y%m%d"}]


def test_two_surname_columns_are_joined_in_order():
    apellidos = fields_of("h2_cifrado.csv")["paciente.apellidos"]
    assert apellidos["from"] == ["APE1", "APE2"] and apellidos["transforms"][0]["op"] == "join_columns"


def test_units_are_read_from_the_values_when_the_label_has_none():
    altura = fields_of("h2_cifrado.csv")["datos_clinicos.altura_cm"]   # TALLA = 1,68
    assert {"op": "scale", "factor": 100} in altura["transforms"]
    assert any("metros" in i or "en m" in i for i in altura["issues"])


def test_mixed_date_formats_in_one_column_are_all_converted():
    fecha = fields_of("h5_excel_dificil.xlsx")["paciente.fecha_nacimiento"]
    assert fecha["transforms"] == [{"op": "date", "from": ["%d/%m/%Y", "%Y-%m-%d"]}]


def test_full_name_column_is_split_into_given_name_and_surnames():
    fields = fields_of("h5_excel_dificil.xlsx")
    for target, part in (("paciente.nombre", "given"), ("paciente.apellidos", "family")):
        f = fields[target]
        assert f["from"] == ["Identificación / Nombre completo"]
        assert f["transforms"] == [{"op": "name_part", "part": part, "surnames": 2}]
        assert any("revisar" in i for i in f["issues"])     # a compound name is the reviewer's call


def test_fhir_official_name_wins_over_nickname_and_phones_tie():
    fields = fields_of("h4_fhir_completo.json")
    assert fields["paciente.nombre"]["from"] == ["name[official].given"]
    assert fields["paciente.nombre"]["transforms"] == [{"op": "join_values", "sep": " "}]
    assert fields["paciente.telefono"]["status"] == "pending"            # home vs mobile: a human chooses
    assert fields["paciente.dni"]["from"] == ["identifier[dni].value"]   # not identifier[dni].type.coding.code


def test_fhir_observations_are_picked_by_loinc_code_with_their_unit():
    rows = rows_of("h4_fhir_completo.json")
    weight = "Observation.valueQuantity.value [Observation.code.coding.code=29463-7]"
    height = "Observation.valueQuantity.value [Observation.code.coding.code=8302-2]"
    assert rows.columns[weight].unit == "kg" and rows.columns[height].unit == "cm"
    fields = fields_of("h4_fhir_completo.json")
    assert fields["datos_clinicos.peso_kg"]["from"] == [weight]
    assert fields["datos_clinicos.altura_cm"]["from"] == [height]


def test_shared_observation_value_column_alone_is_still_pending():
    """Without selectors (the raw shared column), a measurement is never taken blindly."""
    from multibridge.packs.clinical import is_observation as _is_observation
    rows = rows_of("h4_fhir_completo.json")
    assert _is_observation(rows.columns["Observation.valueQuantity.value"])
    assert not _is_observation(rows.columns["Observation.valueQuantity.value [Observation.code.coding.code=8302-2]"])


def test_partial_fhir_birth_date_is_set_aside_not_invented():
    assert {"row": 2, "field": "paciente.fecha_nacimiento"} in ANSWERS["h4_fhir_completo.json"]["rejected"]
