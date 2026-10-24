"""The AI proposer, with a fake model: checks what we send, and that we never trust the reply blindly."""

import json
from pathlib import Path

import pytest

from multibridge import load
from multibridge.ai import ollama
from multibridge.aiview import mask, source_view
from multibridge.expected import Expected
from multibridge.parsers import parse_bytes
from multibridge.proposer import _prompt, propose, propose_ai
from multibridge.records import to_rows

ROOT = Path(__file__).parent.parent
EXPECTED = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")
GOLDEN_HUCA = json.loads((ROOT / "tests" / "golden" / "plans" / "huca_oviedo_hl7v23.json").read_text(encoding="utf-8"))


class FakeModel:
    """Stands in for ollama.chat: records every call, answers from a script."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, model, system, user, schema=None, think=False, **_):
        self.calls.append({"model": model, "user": user, "schema": schema, "think": think})
        answer = self.answers.pop(0) if self.answers else {"fields": []}
        return answer(schema) if callable(answer) else answer


def answer_from(plan: dict, confidence=0.9, **overrides) -> dict:
    fields = [{"target": t, "status": d["status"], "from": d["from"], "confidence": confidence, "why": "test"}
              for t, d in plan.items()]
    for f in fields:
        f.update(overrides.get(f["target"], {}))
    return {"fields": fields}


def huca():
    return to_rows(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"))


def test_model_picks_columns_code_picks_formats():
    fake = FakeModel(answer_from(GOLDEN_HUCA))
    r = propose_ai(huca(), EXPECTED, chat=fake, second_pass=False)
    reduced = {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]} for t, f in r["fields"].items()}
    assert reduced == GOLDEN_HUCA                 # same recipe as the reviewed one, transforms included
    assert r["fields"]["paciente.nombre"]["proposed_by"] == "qwen3:8b"
    assert fake.calls[0]["think"] is False


def test_name_parts_are_joined_given_name_first():
    """qwen3:8b picked PV1-7.2 + PV1-7.3 (surname first); the code fixes the order."""
    fake = FakeModel(answer_from(GOLDEN_HUCA, **{"datos_clinicos.medico_responsable": {"from": ["PV1-7.2", "PV1-7.3"]}}))
    f = propose_ai(huca(), EXPECTED, chat=fake, second_pass=False)["fields"]["datos_clinicos.medico_responsable"]
    assert f["from"] == ["PV1-7.3", "PV1-7.2"]


def test_schema_only_allows_real_columns_and_targets():
    fake = FakeModel(answer_from(GOLDEN_HUCA))
    propose_ai(huca(), EXPECTED, chat=fake, second_pass=False)
    item = fake.calls[0]["schema"]["properties"]["fields"]["items"]["properties"]
    assert set(item["target"]["enum"]) == {t.path for t in EXPECTED.targets}
    assert "PID-5.1" in item["from"]["items"]["enum"] and "_message" not in item["from"]["items"]["enum"]


def test_invented_column_is_dropped_and_field_goes_pending():
    fake = FakeModel(answer_from(GOLDEN_HUCA, **{"paciente.dni": {"from": ["PID-99"]}}))
    f = propose_ai(huca(), EXPECTED, chat=fake, second_pass=False)["fields"]["paciente.dni"]
    assert f["status"] == "pending" and f["from"] == []
    assert any("no existen" in i for i in f["issues"])


def test_one_column_cannot_feed_two_fields():
    fake = FakeModel(answer_from(GOLDEN_HUCA, **{"paciente.dni": {"from": ["PID-3.1"], "confidence": 0.5}}))
    fields = propose_ai(huca(), EXPECTED, chat=fake, second_pass=False)["fields"]
    assert fields["paciente.id"]["from"] == ["PID-3.1"]           # the more confident claim keeps it
    assert fields["paciente.dni"]["status"] == "pending"
    assert any("ya usada" in i for i in fields["paciente.dni"]["issues"])


def test_required_field_is_never_left_as_no_data():
    fake = FakeModel(answer_from(GOLDEN_HUCA, **{"paciente.id": {"status": "no_data", "from": []}}))
    assert propose_ai(huca(), EXPECTED, chat=fake, second_pass=False)["fields"]["paciente.id"]["status"] == "pending"


def test_missing_answer_becomes_pending():
    plan = {t: d for t, d in GOLDEN_HUCA.items() if t != "paciente.telefono"}
    f = propose_ai(huca(), EXPECTED, chat=FakeModel(answer_from(plan)), second_pass=False)["fields"]["paciente.telefono"]
    assert f["status"] == "pending" and "no respondió" in f["issues"][0]


def test_model_translations_are_accepted_only_into_allowed_values():
    raw = "NHC;Nombre;Apellidos;F. Nacimiento;Sexo\nX1;Ana;Pérez;01/01/1980;Fem\nX2;Luis;Gil;02/02/1990;Masc\n"
    rows = to_rows(parse_bytes(raw.encode(), "sexo_raro.csv"))
    plan = {"paciente.id": {"status": "mapped", "from": ["NHC"]}, "paciente.nombre": {"status": "mapped", "from": ["Nombre"]},
            "paciente.apellidos": {"status": "mapped", "from": ["Apellidos"]},
            "paciente.fecha_nacimiento": {"status": "mapped", "from": ["F. Nacimiento"]},
            "paciente.sexo": {"status": "mapped", "from": ["Sexo"]}}
    good = answer_from(plan, **{"paciente.sexo": {"translate": [{"source": "Fem", "target": "female"},
                                                                {"source": "Masc", "target": "male"}]}})
    sexo = propose_ai(rows, EXPECTED, chat=FakeModel(good), second_pass=False)["fields"]["paciente.sexo"]
    assert sexo["status"] == "mapped"
    assert sexo["transforms"][0] == {"op": "translate", "values": {"Fem": "female", "Masc": "male"}}
    assert any("propuesta por la IA" in i for i in sexo["issues"])

    bad = answer_from(plan, **{"paciente.sexo": {"translate": [{"source": "Fem", "target": "mujer"}]}})
    sexo = propose_ai(rows, EXPECTED, chat=FakeModel(bad), second_pass=False)["fields"]["paciente.sexo"]
    assert sexo["status"] == "pending"


def test_observation_values_stay_pending_even_if_the_model_maps_them():
    rows = to_rows(load(ROOT / "examples" / "hospital_a_diagnosticos.hl7"))
    fake = FakeModel({"fields": [{"target": "datos_clinicos.peso_kg", "status": "mapped", "from": ["OBX-5"],
                                  "confidence": 0.95, "why": "peso"}]})
    f = propose_ai(rows, EXPECTED, chat=fake, second_pass=False)["fields"]["datos_clinicos.peso_kg"]
    assert f["status"] == "pending"


def test_doubtful_fields_get_a_second_pass_with_thinking():
    first = answer_from(GOLDEN_HUCA, **{"datos_clinicos.peso_kg": {"confidence": 0.4}})
    second = {"fields": [{"target": "datos_clinicos.peso_kg", "status": "mapped", "from": ["ZPA-3"],
                          "confidence": 0.8, "why": "mediana 70: kg"}]}
    fake = FakeModel(first, second)
    r = propose_ai(huca(), EXPECTED, chat=fake)
    assert [c["think"] for c in fake.calls] == [False, True]
    assert fake.calls[1]["schema"]["properties"]["fields"]["items"]["properties"]["target"]["enum"] == [
        "datos_clinicos.peso_kg"]
    assert r["fields"]["datos_clinicos.peso_kg"]["confidence"] == 0.8
    assert r["proposer"]["second_pass"] == ["datos_clinicos.peso_kg"]


def test_falls_back_to_rules_when_ollama_is_down(monkeypatch):
    def down(*a, **k):
        raise ollama.OllamaUnavailable("no se puede conectar")
    monkeypatch.setattr(ollama, "chat", down)
    monkeypatch.setattr(ollama, "unload", lambda model: None)
    r = propose(huca(), EXPECTED, model="auto")
    assert r["proposer"]["model"] == "rules" and "conectar" in r["proposer"]["fallback_reason"]
    assert r["fields"]["paciente.id"]["from"] == ["PID-3.1"]
    with pytest.raises(ollama.OllamaUnavailable):
        propose(huca(), EXPECTED, model="qwen3:8b")   # an explicit model never silently falls back


def test_ollama_must_be_local(monkeypatch):
    monkeypatch.setenv("MULTIBRIDGE_OLLAMA_URL", "http://ai.example.com:11434")
    with pytest.raises(ValueError, match="C3"):
        ollama.base_url()
    monkeypatch.setenv("MULTIBRIDGE_OLLAMA_URL", "http://localhost:12000")
    assert ollama.base_url() == "http://localhost:12000"


# --- mistakes seen in the real evaluation (docs/EVAL.md), replayed with a fake model -----------------

def leon():
    return to_rows(load(ROOT / "examples" / "hospital_leon_fhir.json"))


GOLDEN_LEON = json.loads((ROOT / "tests" / "golden" / "plans" / "hospital_leon_fhir.json").read_text(encoding="utf-8"))


def test_fhir_metadata_columns_are_never_offered():
    fake = FakeModel(answer_from(GOLDEN_LEON))
    propose_ai(leon(), EXPECTED, chat=fake, second_pass=False)
    enum = fake.calls[0]["schema"]["properties"]["fields"]["items"]["properties"]["from"]["items"]["enum"]
    assert "identifier[mrn].system" not in enum and "telecom[phone].system" not in enum
    assert "identifier[mrn].system" not in fake.calls[0]["user"]


def test_qwen8b_invented_doctor_becomes_pending():
    """qwen3:8b filled León's (absent) doctor with id + identifier.system + identifier.system."""
    bad = answer_from(GOLDEN_LEON, **{"datos_clinicos.medico_responsable": {
        "status": "mapped", "from": ["id", "identifier[mrn].system", "identifier[mrn].system"]}})
    f = propose_ai(leon(), EXPECTED, chat=FakeModel(bad), second_pass=False)["fields"]["datos_clinicos.medico_responsable"]
    assert f["status"] == "pending"
    assert "identifier[mrn].system" not in f["from"]          # metadata is dropped; the reviewer sees the rest
    assert any("id_tecnico" in i for i in f["issues"])


def test_same_column_twice_is_rejected():
    bad = answer_from(GOLDEN_LEON, **{"datos_clinicos.medico_responsable": {"status": "mapped", "from": ["id", "id"]}})
    f = propose_ai(leon(), EXPECTED, chat=FakeModel(bad), second_pass=False)["fields"]["datos_clinicos.medico_responsable"]
    assert f["status"] == "pending" and any("repitió" in i for i in f["issues"])


def test_qwen30b_technical_id_as_patient_id_becomes_pending():
    """qwen3:30b took the FHIR resource id ('p1') instead of the MRN."""
    bad = answer_from(GOLDEN_LEON, **{"paciente.id": {"from": ["id"]}})
    f = propose_ai(leon(), EXPECTED, chat=FakeModel(bad), second_pass=False)["fields"]["paciente.id"]
    assert f["status"] == "pending" and any("id_tecnico" in i for i in f["issues"])


def test_qwen30b_missed_phone_becomes_pending_with_the_rules_suggestion():
    """qwen3:30b said the CSV had no phone, although 'Teléfono móvil' is there."""
    rows = to_rows(load(ROOT / "examples" / "hospital_alvarez_buylla.csv"))
    plan = json.loads((ROOT / "tests" / "golden" / "plans" / "hospital_alvarez_buylla.json").read_text(encoding="utf-8"))
    bad = answer_from(plan, **{"paciente.telefono": {"status": "no_data", "from": []}})
    f = propose_ai(rows, EXPECTED, chat=FakeModel(bad), second_pass=False)["fields"]["paciente.telefono"]
    assert f["status"] == "pending" and any("Teléfono móvil" in i for i in f["issues"])


def test_full_name_column_is_split_for_both_parts_like_the_rules():
    """Both models mapped the messy Excel's 'Nombre y apellidos' into paciente.nombre only. Since phase 7
    the code splits it: the given name and the surnames both come from it, through name_part."""
    rows = to_rows(load(ROOT / "examples" / "hospital_c_messy.xlsx"))
    answer = {"fields": [{"target": "paciente.nombre", "status": "mapped", "from": ["Paciente / Nombre y apellidos"],
                          "confidence": 1.0, "why": "nombre"},
                         {"target": "paciente.apellidos", "status": "no_data", "from": [], "confidence": 0.5}]}
    fields = propose_ai(rows, EXPECTED, chat=FakeModel(answer), second_pass=False)["fields"]
    for target, part in (("paciente.nombre", "given"), ("paciente.apellidos", "family")):
        f = fields[target]
        assert f["status"] == "mapped" and f["from"] == ["Paciente / Nombre y apellidos"]
        assert {"op": "name_part", "part": part, "surnames": 2} in f["transforms"]
    assert any("se separa" in i for i in fields["paciente.apellidos"]["issues"])


def test_rules_never_take_a_diagnosis_column_as_the_doctor():
    from multibridge.matcher import propose as rules_propose
    rows = to_rows(load(ROOT / "examples" / "hospital_c_messy.xlsx"))
    doctor = rules_propose(rows, EXPECTED)["fields"]["datos_clinicos.medico_responsable"]
    assert "Clínica / Diagnóstico principal" not in doctor["from"]


# --- privacy of the prompt (COMPLIANCE C4, C6) --------------------------------------------------------

FILES = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7",
         "hospital_c_messy.xlsx", "hospital_a_diagnosticos.hl7", "hospital_b_condiciones.json"]


@pytest.mark.parametrize("name", FILES)
def test_prompt_never_contains_values_of_uncleared_columns(name):
    rows = to_rows(load(ROOT / "examples" / name))
    prompt = _prompt(rows, EXPECTED, examples=[])
    shown = {c["column"] for c in source_view(rows)["columns"] if "values" in c}
    leaked = []
    for col, f in rows.columns.items():
        if col in shown:
            continue
        for v in rows.values(col):
            for x in v if isinstance(v, list) else [v]:
                if x and len(x) >= 4 and not x.isdigit() and f'"{x}"' in prompt:
                    leaked.append((col, x))
    assert not leaked


@pytest.mark.parametrize("name", FILES)
def test_sensitive_columns_are_never_cleared(name):
    rows = to_rows(load(ROOT / "examples" / name))
    for c in source_view(rows)["columns"]:
        if rows.columns[c["column"]].sensitive:
            assert "values" not in c and "numbers" not in c


def test_destination_example_values_are_masked_too():
    prompt = _prompt(huca(), EXPECTED, examples=[])
    assert "12345678Z" not in prompt and mask("12345678Z") in prompt
    assert '"female"' in prompt          # allowed values stay readable


def test_mask_keeps_shape_not_content():
    assert mask("FERNANDEZ-ALVAREZ, Lucía") == "XXXXXXXXX-XXXXXXX, Xxxxx"
    assert mask("HC-7781") == "XX-9999"


def test_a_list_takes_every_column_the_rules_found():
    """qwen3:8b gave the FHIR Condition list only 'Diagnóstico principal'; 'Otros diagnósticos' belongs too."""
    bundle = Expected.load(ROOT / "expected" / "paciente_resumen_fhir.example.json")
    rows = to_rows(load(ROOT / "examples" / "hospital_c_messy.xlsx"))
    answer = {"fields": [{"target": "Condition.code.text", "status": "mapped",
                          "from": ["Clínica / Diagnóstico principal"], "confidence": 0.9}]}
    f = propose_ai(rows, bundle, chat=FakeModel(answer), second_pass=False)["fields"]["Condition.code.text"]
    assert f["status"] == "mapped" and f["from"] == ["Clínica / Diagnóstico principal", "Clínica / Otros diagnósticos"]
    assert {"op": "split_values", "sep": ";"} in f["transforms"] and any("como en las reglas" in i for i in f["issues"])
