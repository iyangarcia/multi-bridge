"""Phases 7 and 8: the two first translations through the same pipeline, with no per-pair code.

    A. messy Excel -> FHIR Bundle (clinical pack): one row -> a Patient + Observations + one
       Condition per diagnosis + one AllergyIntolerance per allergy, linked by reference.
    B. CSV order lines -> nested JSON and XML (no pack): many rows -> one order with its lines.
"""

import json
from pathlib import Path

import pytest

from multibridge import formats, load
from multibridge.engine import _name_part, run
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.parsers import parse_bytes
from multibridge.recipe import approve
from multibridge.records import to_rows

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "fhir"
BUNDLE = Expected.load(ROOT / "expected" / "paciente_resumen_fhir.example.json")
EXCEL = {"hospital_c_messy.xlsx": ["Clínica / Campo libre 1"], "hard/h5_excel_dificil.xlsx": ["Clínica / Grupo sanguíneo"]}
ORDERS = ROOT / "examples" / "pedidos"
ANSWERS = json.loads((ORDERS / "answers.json").read_text(encoding="utf-8"))["pedidos_lineas.csv"]
ORDER_DESTINATIONS = {"pedido_json": ROOT / "examples" / "destinos" / "pedido_json.example.json",
                      "pedido_xml": ROOT / "examples" / "destinos" / "pedido_xml.example.xml"}


def reduced(draft):
    return {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]} for t, f in draft["fields"].items()}


def accepted(draft):
    """The reviewer accepts the proposal: a pending field with a column keeps it."""
    for f in draft["fields"].values():
        if f["status"] == "pending":
            f["status"] = "mapped" if f["from"] else "no_data"
    return draft


# --- A. messy Excel -> FHIR -------------------------------------------------------------------------

@pytest.mark.parametrize("name", EXCEL)
def test_excel_proposal_is_the_reviewed_plan(name):
    rows = to_rows(load(ROOT / "examples" / name))
    golden = json.loads((GOLDEN / f"{Path(name).stem}.plan.json").read_text(encoding="utf-8"))
    draft = propose(rows, BUNDLE)
    assert reduced(draft) == golden["fields"]
    assert approve(draft, BUNDLE, by="t", carry=EXCEL[name])["extras"]["drop"] == golden["extras"]["drop"]


@pytest.mark.parametrize("name", EXCEL)
def test_excel_becomes_the_reviewed_bundle(name):
    rows = to_rows(load(ROOT / "examples" / name))
    result = run(rows, approve(propose(rows, BUNDLE), BUNDLE, by="t", carry=EXCEL[name]), BUNDLE)
    out = result.write(BUNDLE)
    assert result.rejected == [] and formats.get("fhir").check(out) == []
    assert out == (GOLDEN / f"{Path(name).stem}.bundle.json").read_bytes()


@pytest.mark.parametrize("name", EXCEL)
def test_no_source_column_disappears_without_a_decision(name):
    rows = to_rows(load(ROOT / "examples" / name))
    recipe = approve(propose(rows, BUNDLE), BUNDLE, by="t", carry=EXCEL[name])
    used = {c for f in recipe["fields"].values() for c in f["from"]}
    decided = used | set(recipe["extras"]["carry"]) | set(recipe["extras"]["drop"])
    with_data = {c for c, f in rows.columns.items() if f.dtype != "empty"}
    assert with_data <= decided and recipe["extras"]["by"] == "t"


def test_one_row_becomes_a_patient_and_its_linked_resources():
    bundle = json.loads((GOLDEN / "hospital_c_messy.bundle.json").read_text(encoding="utf-8"))
    entries = bundle["entry"]
    first = entries[0]["fullUrl"]
    mine = [e["resource"] for e in entries[1:6]]
    assert [r["resourceType"] for r in mine] == ["Observation", "Observation", "Condition", "Condition", "Condition"]
    assert [r["code"]["text"] for r in mine[2:]] == ["DM2 mal controlada", "HTA", "DLP"]   # "HTA; DLP" split
    assert all(r["subject"]["reference"] == first for r in mine)
    assert len({e["fullUrl"] for e in entries}) == len(entries)
    loinc = {r["code"]["coding"][0]["code"]: r["valueQuantity"]["code"] for r in mine[:2]}
    assert loinc == {"29463-7": "kg", "8302-2": "cm"}
    # free-text diagnoses stay text: no code is made up (COMPLIANCE C10)
    assert all("coding" not in r["code"] for r in mine[2:])


def test_a_resource_with_no_data_and_an_empty_part_are_left_out():
    bundle = json.loads((GOLDEN / "hospital_c_messy.bundle.json").read_text(encoding="utf-8"))
    types = {e["resource"]["resourceType"] for e in bundle["entry"]}
    assert "AllergyIntolerance" not in types       # the hospital C sheet has no allergies
    patient = bundle["entry"][0]["resource"]
    assert "telecom" not in patient and "address" not in patient   # not {"system": "phone"} with no number


def test_full_names_are_split_with_their_particles():
    assert _name_part("Lucía María Álvarez Castro", "given", 2) == "Lucía María"
    assert _name_part("Lucía María Álvarez Castro", "family", 2) == "Álvarez Castro"
    assert _name_part("Ana de la Fuente Gil", "family", 2) == "de la Fuente Gil"
    assert _name_part("Ana de la Fuente Gil", "given", 2) == "Ana"
    assert _name_part("Ana Gil", "family", 2) == "Gil"
    assert _name_part("Ana", "family", 2) is None


# --- B. CSV order lines -> nested JSON / XML, no pack ----------------------------------------------

def grade(draft, plan):
    counts = {"right": 0, "pending": 0, "wrong": 0}
    for target, truth in plan.items():
        f = draft["fields"][target]
        if f["status"] == "pending":
            counts["pending"] += 1
        elif (f["status"], f["from"]) == (truth["status"], truth["from"]):
            counts["right"] += 1
        else:
            counts["wrong"] += 1
    return counts


@pytest.mark.parametrize("dest", ORDER_DESTINATIONS)
def test_order_proposal_with_no_pack_is_never_wrong(dest):
    e = Expected.load(ORDER_DESTINATIONS[dest])
    assert e.pack is None
    draft = propose(to_rows(load(ORDERS / "pedidos_lineas.csv")), e)
    counts = grade(draft, ANSWERS[dest]["plan"])
    assert counts == {"right": 9, "pending": 2, "wrong": 0}
    # what stays pending is a guess the reviewer confirms, and it already points at the right column
    for target, f in draft["fields"].items():
        if f["status"] == "pending":
            assert f["from"] == ANSWERS[dest]["plan"][target]["from"] and any("revisar" in i for i in f["issues"])


@pytest.mark.parametrize("dest", ORDER_DESTINATIONS)
def test_order_lines_become_nested_orders(dest):
    e = Expected.load(ORDER_DESTINATIONS[dest])
    rows = to_rows(load(ORDERS / "pedidos_lineas.csv"))
    result = run(rows, approve(accepted(propose(rows, e)), e, by="t", carry=["Comercial"]), e)
    assert [r["row"] for r in result.rejected] == ANSWERS[dest]["rejected_rows"]   # the line with no order number
    assert result.report["items"] == 3 and result.report["custom_fields"]["dropped"] == ["Nota interna"]
    assert [{k: v for k, v in r.items() if k != "_extras"} for r in result.records] == ANSWERS[dest]["items"]
    out = result.write(e)
    assert formats.get(e.format).check(out) == []


def test_nested_xml_reads_back():
    e = Expected.load(ORDER_DESTINATIONS["pedido_xml"])
    rows = to_rows(load(ORDERS / "pedidos_lineas.csv"))
    out = run(rows, approve(accepted(propose(rows, e)), e, by="t"), e).write(e)
    back = to_rows(parse_bytes(out, "salida.xml"))
    assert [r["@numero"] for r in back.rows] == ["PED-1001", "PED-1002", "PED-1003"]
    assert back.rows[2]["lineas.linea.referencia"] == ["C-25", "G-02", "P-10"]
    assert "<precio_unitario>6.80</precio_unitario>" in out.decode()   # written like the example (2 decimals)


def test_name_words_match_without_a_vocabulary():
    from multibridge.matcher import name_match
    e = Expected.load(ORDER_DESTINATIONS["pedido_xml"])
    t = {x.path: x for x in e.targets}
    assert name_match("NIF cliente", t["pedido.cliente.nif"])[0] >= 0.9           # its name + the object it sits in
    assert name_match("Num. pedido", t["pedido.@numero"])[0] >= 0.8               # a cut word
    assert name_match("NIF cliente", t["pedido.cliente.email"])[0] == 0
    assert name_match("Cliente", t["pedido.cliente.nombre"])[2]                   # named after the object: a guess
    assert name_match("% Dto.", t["pedido.lineas.linea[].descuento_pct"])[2]      # an abbreviation: a guess


def test_the_cli_default_destination_is_still_the_original_one():
    """expected/ holds several examples since phase 7: with no --expected the CLI keeps cdss_paciente."""
    from multibridge.expected import default_destination
    assert default_destination(ROOT / "expected").name == "cdss_paciente.example.json"
