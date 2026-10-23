"""Phase 6: the destination is an example in any format, and the output is written in that format.

Any reader -> any writer through an approved recipe, every writer's output passes its checker,
many rows -> one item, one row -> several parts, and no unused source field disappears silently.
"""

import base64
import io
import json
from pathlib import Path

import pytest

from multibridge import formats, load
from multibridge.engine import run
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.output import EXTRAS
from multibridge.parsers import parse_bytes
from multibridge.recipe import ApprovalError, approve, compatible
from multibridge.records import to_rows

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "examples" / "destinos"
SOURCES = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7"]


def reviewed(rows, expected, carry=None):
    """What a reviewer does when they accept the proposal: pending fields with a column are kept,
    the others continue without data."""
    draft = propose(rows, expected)
    for f in draft["fields"].values():
        if f["status"] == "pending":
            f["status"] = "mapped" if f["from"] else "no_data"
    return approve(draft, expected, by="test", carry=carry)


def excel_destination() -> Expected:
    from openpyxl import Workbook
    import datetime as dt
    wb = Workbook()
    ws = wb.active
    ws.title = "Pacientes"
    ws.append(["NHC", "Nombre", "Fecha de nacimiento", "Talla (cm)"])
    ws.append(["HC-1", "Ana", dt.date(1980, 5, 1), 168])
    buf = io.BytesIO()
    wb.save(buf)
    return Expected.from_bytes(buf.getvalue(), "pacientes.example.xlsx", rules={"$pack": "clinical"})


def destinations() -> dict[str, Expected]:
    out = {"json": Expected.load(ROOT / "expected" / "cdss_paciente.example.json")}
    for p in sorted(DEST.glob("*.example.*")):
        out[p.name] = Expected.load(p)
    out["excel"] = excel_destination()
    return out


DESTINATIONS = destinations()


def test_the_original_destination_keeps_its_id():
    """Recipes approved before phase 6 must keep matching."""
    assert DESTINATIONS["json"].id == "cdss_paciente#0ac41f7c" and DESTINATIONS["json"].format == "json"


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("dest", list(DESTINATIONS))
def test_any_reader_to_any_writer(source, dest):
    expected = DESTINATIONS[dest]
    rows = to_rows(load(ROOT / "examples" / source))
    result = run(rows, reviewed(rows, expected), expected)
    assert result.rejected == [] and len(result.items) == len(rows.rows)
    data = result.write(expected)
    assert formats.get(expected.format).check(data) == []


def test_fhir_destination_is_a_template():
    e = DESTINATIONS["paciente_fhir.example.json"]
    by = {t.path: t for t in e.targets}
    assert e.format == "fhir" and e.pack == "clinical"
    weight, height = by["Observation[29463-7].valueQuantity.value"], by["Observation[8302-2].valueQuantity.value"]
    assert (weight.concept, weight.unit, weight.type) == ("peso", "kg", "number")
    assert (height.concept, height.unit, height.type) == ("altura", "cm", "number")
    assert by["Patient.gender"].enum == ["male", "female", "other", "unknown"]
    # structure, not data: never a target
    assert "Patient.identifier.system" in e.constants and "Observation[29463-7].status" in e.constants
    assert not any(p.endswith((".system", ".reference", "resourceType")) for p in by)


def test_fhir_writer_new_ids_rewired_references_and_no_empty_resources():
    e = DESTINATIONS["paciente_fhir.example.json"]
    rows = to_rows(parse_bytes("NHC;Nombre;Apellidos\nHC-1;Ana;Ruiz\nHC-2;Luis;Gil\n".encode(), "x.csv"))
    bundle = json.loads(run(rows, reviewed(rows, e), e).write(e))   # no weight or height in the source
    kinds = [x["resource"]["resourceType"] for x in bundle["entry"]]
    assert kinds == ["Patient"] * len(rows.rows)          # Observations with no value are left out
    urls = [x["fullUrl"] for x in bundle["entry"]]
    assert len(set(urls)) == len(urls) and all(u.startswith("urn:uuid:") for u in urls)
    rows = to_rows(load(ROOT / "examples" / "hospital_alvarez_buylla.csv"))
    bundle = json.loads(run(rows, reviewed(rows, e), e).write(e))
    patients = {x["fullUrl"] for x in bundle["entry"] if x["resource"]["resourceType"] == "Patient"}
    refs = [x["resource"]["subject"]["reference"] for x in bundle["entry"] if x["resource"]["resourceType"] == "Observation"]
    assert refs and set(refs) <= patients and len(set(refs)) == len(patients)
    broken = json.dumps({"resourceType": "Bundle", "type": "collection", "entry": [
        {"fullUrl": "urn:uuid:a", "resource": {"resourceType": "Observation", "status": "final", "code": {},
                                               "subject": {"reference": "urn:uuid:zz"}}}]}).encode()
    assert any("referencia" in p for p in formats.get("fhir").check(broken))


def test_tabular_output_looks_like_the_example():
    e = DESTINATIONS["paciente_tabla.example.csv"]
    rows = to_rows(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"))
    text = run(rows, reviewed(rows, e), e).write(e).decode("utf-8")
    header, first = text.splitlines()[:2]
    assert header == "Nº historia;Nombre;Apellidos;F. nacimiento;Sexo;Peso (kg)"
    # title case and dd/mm/yyyy like the example, sex in the destination's own catalogue, decimal comma
    assert first == "NHC-10234;Lucia;Fernandez Alvarez;12/04/1985;Mujer;58,5"


# --- many rows -> one item ------------------------------------------------------------------------

LINES = """Numero;Fecha;Cliente;Producto;Cantidad;Precio
P-1;05/03/2026;Ana Ruiz;Leche;2;1,10
P-1;05/03/2026;Ana Ruiz;Pan;1;0,90
P-2;06/03/2026;Luis Gil;Huevos;12;0,25
""".encode()
ORDER = {"numero": "P-9", "fecha": "2026-01-01", "cliente": "Nombre Apellido",
         "lineas": [{"producto": "Algo", "cantidad": 1, "precio": 2.5}]}
XML_ORDER = b"""<pedidos><pedido numero="P-9"><fecha>01/01/2026</fecha><cliente>Nombre Apellido</cliente>
<lineas><linea><producto>Algo</producto><cantidad>1</cantidad><precio>2.50</precio></linea>
<linea><producto>Otro</producto><cantidad>3</cantidad><precio>1.00</precio></linea></lineas></pedido></pedidos>"""


def order_recipe(rows, e):
    return reviewed(rows, e)


def test_many_rows_become_one_nested_item_json():
    e = Expected.from_example(ORDER, "pedido", rules={"$group_by": "numero"})
    assert e.groups == ["lineas[]"] and e.get("lineas[].producto").group == "lineas[]"
    rows = to_rows(parse_bytes(LINES, "lineas.csv"))
    result = run(rows, order_recipe(rows, e), e)
    assert result.report["items"] == 2 and result.report["accepted"] == 3
    assert result.records[0] == {"numero": "P-1", "fecha": "2026-03-05", "cliente": "Ana Ruiz", "lineas": [
        {"producto": "Leche", "cantidad": 2, "precio": 1.1}, {"producto": "Pan", "cantidad": 1, "precio": 0.9}]}
    assert json.loads(result.write(e)) == result.records


def test_many_rows_become_one_nested_item_xml():
    e = Expected.from_bytes(XML_ORDER, "pedido.example.xml", rules={"$group_by": "pedido.@numero"})
    rows = to_rows(parse_bytes(LINES, "lineas.csv"))
    out = run(rows, order_recipe(rows, e), e).write(e)
    assert formats.get("xml").check(out) == []
    text = out.decode()
    assert text.count("<pedido ") == 2 and text.count("<linea>") == 3
    assert "<precio>1.10</precio>" in text and "<fecha>05/03/2026</fecha>" in text   # as the example writes them
    # and back: the XML reader reads what the XML writer wrote
    back = to_rows(parse_bytes(out, "salida.xml"))
    assert [r["@numero"] for r in back.rows] == ["P-1", "P-2"]
    assert back.rows[0]["lineas.linea.producto"] == ["Leche", "Pan"]


def test_rows_of_one_group_must_agree():
    e = Expected.from_example(ORDER, "pedido", rules={"$group_by": "numero"})
    clash = LINES.replace(b"P-1;05/03/2026;Ana Ruiz;Pan", b"P-1;05/03/2026;Otra Persona;Pan")
    rows = to_rows(parse_bytes(clash, "lineas.csv"))
    result = run(rows, order_recipe(rows, e), e)
    assert [r["row"] for r in result.rejected] == [0, 1] and len(result.items) == 1
    assert result.rejected[0]["errors"] == [{"field": "cliente", "reason": "valores distintos en filas del mismo grupo"}]
    with pytest.raises(ValueError, match="group_by"):
        Expected.from_example(ORDER, "pedido", rules={"$group_by": "lineas[].producto"})


def test_a_target_with_several_values():
    e = Expected.from_example({"nhc": "HC-1", "alergias": ["Penicilina", "Polen"]}, "p", rules={"$pack": "clinical"})
    assert e.get("alergias").multiple == "list"
    rows = to_rows(load(ROOT / "examples" / "hospital_b_condiciones.json"))
    draft = propose(rows, e)
    draft["fields"]["alergias"].update(status="mapped", **{"from": ["Condition.code.text"], "transforms": []})
    draft["fields"]["nhc"].update(status="no_data", **{"from": []})
    result = run(rows, approve(draft, e, by="t"), e)
    assert any(isinstance(r["alergias"], list) and len(r["alergias"]) > 1 for r in result.records)


# --- custom fields: carried or dropped, never silently ----------------------------------------------

def test_unused_fields_are_dropped_on_record_or_carried_into_every_format():
    rows = to_rows(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"))
    for dest in ("json", "paciente_fhir.example.json", "paciente_tabla.example.csv", "paciente_xml.example.xml"):
        e = DESTINATIONS[dest]
        draft = propose(rows, e)
        for f in draft["fields"].values():
            if f["status"] == "pending":
                f["status"] = "mapped" if f["from"] else "no_data"
        unused = draft["unmatched"]
        carry = "ZPA-2" if "ZPA-2" in unused else next(c for c in unused if isinstance(rows.rows[0].get(c), str))
        r = approve(draft, e, by="Ana", carry=[carry])
        assert r["extras"] == {"carry": [carry], "drop": [c for c in unused if c != carry], "by": "Ana"}
        result = run(rows, r, e)
        assert result.report["custom_fields"]["carried"] == [carry]
        assert result.items[0][EXTRAS][carry]
        out = result.write(e)
        assert formats.get(e.format).check(out) == []
        value = str(result.items[0][EXTRAS][carry])
        assert value in out.decode("utf-8"), dest
    with pytest.raises(ApprovalError, match="ya se usa"):
        approve(draft, e, by="Ana", carry=[draft["fields"]["paciente.@nhc"]["from"][0]])
    # a file without the carried column can't reuse the recipe
    other = to_rows(load(ROOT / "examples" / "hospital_alvarez_buylla.csv"))
    assert any("campo extra" in why for why in compatible(r, other, e))


def test_recipes_approved_before_phase_6_still_run():
    e = DESTINATIONS["json"]
    rows = to_rows(load(ROOT / "examples" / "huca_oviedo_hl7v23.hl7"))
    r = reviewed(rows, e)
    old = {k: v for k, v in r.items() if k != "extras"}
    from multibridge.recipe import plan_hash
    old["approval"] = {**r["approval"], "sha256": plan_hash(old)}
    result = run(rows, old, e)
    assert result.rejected == [] and "custom_fields" not in result.report


def test_xml_with_doctype_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "xx">]><a><b>&x;</b></a>'
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_bytes(bomb, "x.xml")
    assert formats.get("xml").check(bomb)


# --- the API ----------------------------------------------------------------------------------------

def test_api_destinations_and_output_in_the_destination_format(tmp_path):
    import shutil
    import threading
    from test_api import call
    from multibridge.api import make_server

    for folder in ("web", "expected", "examples"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    srv = make_server(tmp_path, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    server = (srv, tmp_path)
    try:
        status, dests = call(server, "GET", "/api/destinations")
        keys = {d["key"]: d for d in dests}
        assert status == 200 and keys["cdss_paciente"]["origin"] == "carpeta"
        assert keys["ejemplo-paciente_fhir"]["format"] == "fhir"
        csv_example = (DEST / "paciente_tabla.example.csv").read_bytes()
        rules = json.loads((DEST / "paciente_tabla.rules.json").read_text(encoding="utf-8"))
        status, up_dest = call(server, "POST", "/api/destination", {
            "name": "tabla.example.csv", "content_b64": base64.b64encode(csv_example).decode(), "rules": rules})
        assert status == 200 and up_dest["format"] == "csv" and up_dest["key"].startswith("subido-")
        status, up = call(server, "POST", "/api/upload", {"example": "huca_oviedo_hl7v23.hl7"})
        key = up_dest["key"]
        status, prop = call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "rules",
                                                              "destination": key})
        assert status == 200 and prop["draft"]["expected"] == up_dest["id"]
        # regression: recomputing a field after a column change uses the destination's pack
        status, field = call(server, "POST", "/api/field", {"upload_id": up["upload_id"], "target": "Sexo",
                                                            "from": ["PID-8"], "destination": key})
        assert {"op": "translate", "values": {"F": "Mujer", "M": "Hombre"}} in field["transforms"]
        decisions = {"fields": {t: {"status": "mapped" if f["from"] else "no_data", "from": f["from"],
                                    "transforms": f["transforms"]} for t, f in prop["draft"]["fields"].items()}}
        status, other = call(server, "POST", "/api/approve", {"upload_id": up["upload_id"], "draft": decisions,
                                                              "by": "Ana", "destination": "cdss_paciente"})
        assert status == 409   # proposed for one destination, approved for another: refused
        status, ok = call(server, "POST", "/api/approve", {"upload_id": up["upload_id"], "draft": decisions,
                                                           "by": "Ana", "destination": key, "carry": []})
        assert status == 200 and ok["output"]["format"] == "csv" and ok["output"]["problems"] == []
        text = base64.b64decode(ok["output"]["content_b64"]).decode("utf-8")
        assert text.startswith("Nº historia;Nombre;Apellidos") and ok["recipe"]["recipe"].endswith("-tabla")
        assert ok["recipe"]["extras"]["by"] == "Ana"
    finally:
        srv.shutdown()
        srv.server_close()
