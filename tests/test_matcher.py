from pathlib import Path

from multibridge import load
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.records import to_rows

ROOT = Path(__file__).parent.parent
EXPECTED = Expected.load(ROOT / "expected" / "cdss_paciente.example.json")


def proposal(name):
    return propose(to_rows(load(ROOT / "examples" / name)), EXPECTED)


def test_doctor_surname_is_not_the_patient_surname():
    r = proposal("huca_oviedo_hl7v23.hl7")
    assert r["fields"]["paciente.apellidos"]["from"] == ["PID-5.1"]
    doctor = r["fields"]["datos_clinicos.medico_responsable"]
    assert doctor["from"] == ["PV1-7.3", "PV1-7.2"]   # given + family
    assert doctor["transforms"][0] == {"op": "join_columns", "sep": " "}


def test_undocumented_z_segment_is_recognised_by_its_values_and_flagged():
    r = proposal("huca_oviedo_hl7v23.hl7")
    for target, column in [("datos_clinicos.grupo_sanguineo", "ZPA-2"), ("datos_clinicos.peso_kg", "ZPA-3"),
                           ("datos_clinicos.altura_cm", "ZPA-4")]:
        f = r["fields"][target]
        assert f["from"] == [column]
        assert "deducido solo por los valores: revisar" in f["issues"]
        assert any("personalizado" in i for i in f["issues"])


def test_fhir_metadata_never_wins_over_the_value():
    r = proposal("hospital_leon_fhir.json")
    assert r["fields"]["paciente.id"]["from"] == ["identifier[mrn].value"]
    assert r["fields"]["paciente.telefono"]["from"] == ["telecom[phone].value"]


def test_fhir_allergy_resource_reaches_the_patient_row():
    r = proposal("hospital_b_condiciones.json")
    assert r["fields"]["datos_clinicos.alergia"]["from"] == ["AllergyIntolerance.code.text"]


def test_observation_values_are_picked_by_their_loinc_code():
    fields = proposal("hospital_a_diagnosticos.hl7")["fields"]
    assert fields["datos_clinicos.peso_kg"]["from"] == ["OBX-5 [OBX-3.1=29463-7]"]
    assert fields["datos_clinicos.altura_cm"]["from"] == ["OBX-5 [OBX-3.1=8302-2]"]


def test_identifiers_without_a_type_code_stay_pending():
    """'NHC-20001^^^HUCA~ASTU123456^^^SESPA': two identifiers and no PID-3.5 to tell them apart."""
    pid = proposal("hospital_a_diagnosticos.hl7")["fields"]["paciente.id"]
    assert pid["status"] == "pending" and any("PID-3.5" in i for i in pid["issues"])


def test_every_target_appears_and_unused_columns_are_listed():
    r = proposal("hospital_leon_fhir.json")
    assert list(r["fields"]) == [t.path for t in EXPECTED.targets]
    assert r["fields"]["direccion.codigo_postal"]["status"] == "no_data"
    assert {"address.country", "id"} <= set(r["unmatched"])


def test_confidence_is_labelled_as_uncalibrated():
    assert "no es una probabilidad" in proposal("hospital_alvarez_buylla.csv")["confidence_kind"]
