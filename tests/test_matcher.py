from pathlib import Path

from multibridge import load
from multibridge.contract import Contract
from multibridge.matcher import propose

ROOT = Path(__file__).parent.parent
CONTRACT = Contract.load(ROOT / "contracts" / "cdss_paciente.v1.json")


def mapping(plan, target):
    return next(m for m in plan["mappings"] if m["target"] == target)


def test_doctor_surname_is_not_the_patient_surname():
    plan = propose(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"), CONTRACT)
    assert [s["path"] for s in mapping(plan, "paciente.apellidos")["sources"]] == ["PID-5.1"]
    doctor = mapping(plan, "datos_clinicos.medico_responsable")
    assert [s["path"] for s in doctor["sources"]] == ["PV1-7.3", "PV1-7.2"]   # given + family
    assert doctor["ops"][0] == {"op": "concat", "sep": " "}


def test_undocumented_z_segment_is_recognised_by_its_values_and_flagged():
    plan = propose(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"), CONTRACT)
    for target, path in [("datos_clinicos.grupo_sanguineo", "ZPA-2"), ("datos_clinicos.peso_kg", "ZPA-3"),
                         ("datos_clinicos.altura_cm", "ZPA-4")]:
        m = mapping(plan, target)
        assert [s["path"] for s in m["sources"]] == [path]
        assert "deducido solo por los valores: revisar" in m["issues"]
        assert any("personalizado" in i for i in m["issues"])


def test_fhir_metadata_never_wins_over_the_value():
    plan = propose(load(ROOT / "examples" / "hospital_leon_fhir.json"), CONTRACT)
    assert mapping(plan, "paciente.id")["sources"][0]["path"] == "identifier[mrn].value"
    assert mapping(plan, "paciente.telefono")["sources"][0]["path"] == "telecom[phone].value"


def test_observation_values_need_a_code_filter_and_block_approval():
    plan = propose(load(ROOT / "examples" / "hospital_a_diagnosticos.hl7"), CONTRACT)
    peso = mapping(plan, "datos_clinicos.peso_kg")
    assert peso["status"] == "pending"
    assert any("filtrar por código" in i for i in peso["issues"])


def test_every_target_appears_and_unused_sources_are_listed():
    plan = propose(load(ROOT / "examples" / "hospital_leon_fhir.json"), CONTRACT)
    assert [m["target"] for m in plan["mappings"]] == [f.path for f in CONTRACT.fields]
    assert mapping(plan, "direccion.codigo_postal")["status"] == "no_source"
    unused = {u["path"] for u in plan["unmatched_sources"]}
    assert "address.country" in unused and "id" in unused


def test_scores_are_labelled_as_uncalibrated():
    plan = propose(load(ROOT / "examples" / "hospital_alvarez_buylla.csv"), CONTRACT)
    assert "no es una probabilidad" in plan["score_kind"]
