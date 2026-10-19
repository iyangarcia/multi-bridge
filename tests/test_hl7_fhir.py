import pytest

from multibridge import load
from multibridge.parsers import parse_bytes
from multibridge.parsers.hl7v2 import HL7Error


# --- HL7 v2 -------------------------------------------------------------------------------------

def test_hl7_original_example(examples):
    ds = load(examples / "huca_oviedo_hl7v23.hl7")
    assert ds.format == "hl7v2"
    pid = ds.tables["PID"]
    assert len(pid) == 8
    assert pid[0]["PID-5.1"] == "FERNANDEZ ALVAREZ"
    assert pid[0]["PID-5.2"] == "LUCIA"
    assert ds.tables["MSH"][0]["MSH-9.1"] == "ADT"           # MSH numbering is off by one in naive parsers
    assert ds.tables["MSH"][0]["MSH-12"] == "2.3"
    assert ds.get("PID", "PID-7").format == "yyyymmdd"
    zpa = ds.get("ZPA", "ZPA-2")
    assert zpa.custom and zpa.kind == "categorical"
    assert ds.get("MSH", "MSH-9.2").dtype == "string", "event A01 is not an ICD-10 code"


def test_hl7_repetitions_escapes_and_repeated_segments(examples):
    ds = load(examples / "hospital_a_diagnosticos.hl7")
    first = ds.tables["PID"][0]
    assert first["PID-3.1"] == ["NHC-20001", "ASTU123456"]   # ~ repetition
    assert first["PID-13"] == ["+34600111999", "+34985000111"]

    dg1 = ds.tables["DG1"]
    assert len(dg1) == 8
    assert {r["_message"] for r in dg1} == {"MSG1001", "MSG1002", "MSG1003"}
    texts = [r.get("DG1-4") for r in dg1]
    assert "Sospecha de NAC & derrame pleural" in texts     # \T\ escape
    assert "AP de IAM\nHTA" in texts                         # \.br\ escape
    assert ds.tables["AL1"][0]["AL1-5"] == ["Urticaria", "Disnea"]


def test_hl7_coding_system_field_is_not_a_diagnosis(examples):
    ds = load(examples / "hospital_a_diagnosticos.hl7")
    assert ds.get("DG1", "DG1-3.1").kind == "clinical_concept"
    system = ds.get("DG1", "DG1-3.3")                        # "I10" = ICD-10, not hypertension
    assert system.kind == "categorical" and system.concepts is None


def test_hl7_newline_separators_and_custom_encoding_chars():
    raw = b"MSH#*~\\&#APP#FAC#####ADT*A01#M1#P#2.3\nPID#1##ID9##DOE*JANE\n"
    ds = parse_bytes(raw, "x.txt")
    assert ds.tables["PID"][0]["PID-5.1"] == "DOE"


def test_hl7_without_msh_is_rejected():
    with pytest.raises(HL7Error):
        parse_bytes(b"PID|1||X", "bad.hl7")


# --- FHIR ---------------------------------------------------------------------------------------

def test_fhir_patient_paths_slices_and_extensions(examples):
    ds = load(examples / "hospital_leon_fhir.json")
    assert ds.format == "fhir"
    p = ds.tables["Patient"][0]
    assert p["name.family"] == "Rodriguez Diaz"
    assert p["identifier[mrn].value"] == "MRN-55001"
    assert p["telecom[phone].value"] == "+34611222333"
    assert p["extension[grupo-sanguineo]"] == "A-"

    dni = ds.get("Patient", "extension[dni]")
    assert dni.custom and dni.sensitive and "hule.sacyl.es" in dni.description
    assert not ds.get("Patient", "identifier[mrn].system").sensitive
    assert ds.get("Patient", "gender").categories == ["female", "male"]


def test_fhir_conditions_mix_icd10_snomed_and_text(examples):
    ds = load(examples / "hospital_b_condiciones.json")
    assert set(ds.tables) == {"Patient", "Condition", "AllergyIntolerance"}
    assert len(ds.tables["Condition"]) == 4
    text = ds.get("Condition", "code.text")
    assert text.kind == "clinical_concept"
    assert ds.get("Condition", "extension[servicio-origen]").custom
    assert ds.get("Condition", "verificationStatus.coding.code").categories == ["confirmed", "provisional"]


def test_ndjson_bulk_export():
    raw = b'{"resourceType":"Patient","id":"a","gender":"male"}\n{"resourceType":"Patient","id":"b","gender":"female"}\n'
    ds = parse_bytes(raw, "Patient.ndjson")
    assert [r["id"] for r in ds.tables["Patient"]] == ["a", "b"]
