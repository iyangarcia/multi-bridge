"""One flat row per patient: joins belong to reading, not to the engine."""

from pathlib import Path

from multibridge import load
from multibridge.parsers import parse_bytes
from multibridge.records import to_rows

ROOT = Path(__file__).parent.parent


def test_hl7_one_row_per_message_with_segments_side_by_side():
    rows = to_rows(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"))
    assert rows.root == "PID" and len(rows.rows) == 8
    first = rows.rows[0]
    assert (first["PID-5.1"], first["PV1-7.2"], first["AL1-3.2"], first["ZPA-2"]) == (
        "FERNANDEZ ALVAREZ", "MARTINEZ", "Penicilina", "A+")
    assert "AL1-3.2" not in rows.rows[2]          # message 3 has no AL1: no value, not an empty string


def test_hl7_repeated_segments_become_a_list():
    rows = to_rows(load(ROOT / "examples" / "hospital_a_diagnosticos.hl7"))
    assert rows.rows[0]["DG1-4"] == ["Sospecha de NAC & derrame pleural", "AP de IAM\nHTA"]
    assert rows.rows[0]["OBX-5"] == ["66.5", "162"]
    assert rows.rows[2]["AL1-5"] == ["Urticaria", "Disnea"]


def test_hl7_rows_do_not_mix_messages():
    rows = to_rows(load(ROOT / "examples" / "hospital_a_diagnosticos.hl7"))
    assert [r["MSH-10"] for r in rows.rows] == ["MSG1001", "MSG1002", "MSG1003"]
    assert rows.rows[1]["DG1-4"] == ["IRA", "DiabA"]


def test_fhir_patient_row_includes_resources_that_reference_it():
    rows = to_rows(load(ROOT / "examples" / "hospital_b_condiciones.json"))
    assert rows.root == "Patient" and len(rows.rows) == 1
    row = rows.rows[0]
    assert row["name.family"] == "Robles Abad"
    assert row["Condition.code.text"] == ["DM2", "Sospecha de neumonía", "HTA", "EPOC"]
    assert row["AllergyIntolerance.code.text"] == "Penicilina"


def test_spreadsheet_uses_the_main_table_and_notes_the_rest():
    rows = to_rows(load(ROOT / "examples" / "hospital_c_messy.xlsx"))
    assert rows.root == "Ingresos" and len(rows.rows) == 6
    assert any("Leyenda triaje" in n and "se ignora" in n for n in rows.notes)


def test_columns_keep_their_profile():
    rows = to_rows(parse_bytes("NHC;DNI\nX1;12345678Z\nX2;87654321X\n".encode(), "t.csv"))
    assert rows.columns["DNI"].sensitive
    assert rows.values("NHC") == ["X1", "X2"]
