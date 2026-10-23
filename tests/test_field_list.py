"""Destinations with no example: a format plus a field list, typed by hand or taken from the source
("receive all the fields"). The person can rename, retype, leave out or add fields."""

import base64
import json
import shutil
from pathlib import Path

import pytest

from multibridge import formats
from multibridge.api import ApiError, App, Handler
from multibridge.expected import Expected, fields_from_rows
from multibridge.parsers import parse_bytes
from multibridge.records import to_rows

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7"]
BLANK = ["json", "csv", "excel", "xml"]


@pytest.fixture
def app(tmp_path):
    for folder in ("web", "expected", "examples"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    return App(tmp_path)


def rows_of(name):
    return to_rows(parse_bytes((ROOT / "examples" / name).read_bytes(), name))


def accept(app, up, dest):
    """Propose and approve as a reviewer who accepts everything (pending with a column -> mapped)."""
    prop = app.do_propose({"upload_id": up["upload_id"], "destination": dest["key"], "model": "rules"})
    decisions = {"fields": {t: {"status": "mapped" if f["from"] else "no_data", "from": f["from"],
                                "transforms": f["transforms"]} for t, f in prop["draft"]["fields"].items()}}
    return prop, app.approve({"upload_id": up["upload_id"], "draft": decisions, "by": "test", "destination": dest["key"]})


def test_formats_say_which_need_no_example(app):
    blank = {f["name"] for f in app.list_formats() if f["blank"]}
    assert blank == set(BLANK)   # FHIR and HL7 v2 take their shape from an example


def test_all_fields_are_typed_only_where_it_cannot_go_wrong():
    huca = {f["name"]: f for f in fields_from_rows(rows_of("huca_oviedo_hl7v23.hl7"))}
    assert huca["PID-7"]["type"] == "date"
    for digits in ("PID-11.5", "MSH-12", "PV1-3.3", "PID-13", "PID-1"):   # postcode, version, bed, phone, sequence
        assert huca[digits]["type"] == "string", digits
    assert not any(n.startswith("_") for n in huca)
    alvarez = {f["name"]: f for f in fields_from_rows(rows_of("hospital_alvarez_buylla.csv"))}
    assert alvarez["F. Nacimiento"]["type"] == "date"
    assert alvarez["Peso (kg)"]["type"] in ("number", "integer") and alvarez["Talla (cm)"]["type"] in ("number", "integer")
    assert all(f["from"] == n for n, f in alvarez.items())


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("fmt", BLANK)
def test_all_fields_into_any_plain_format(app, source, fmt):
    up = app.upload({"example": source})
    fields = app.source_fields({"upload_id": up["upload_id"]})["fields"]
    dest = app.fields_destination({"format": fmt, "fields": fields, "upload_id": up["upload_id"]})
    assert dest["format"] == fmt and len(dest["targets"]) == len(fields)
    prop, ok = accept(app, up, dest)
    assert all(f["proposed_by"] == "direct" and f["status"] == "mapped" for f in prop["draft"]["fields"].values())
    assert prop["draft"]["unmatched"] == []
    rep = ok["report"]
    assert rep["accepted"] == rep["rows"] == 8 and rep["errors"] == []
    out = ok["output"]
    assert out["problems"] == [] and out["format"] == fmt
    data = base64.b64decode(out["content_b64"])
    back = to_rows(parse_bytes(data, out["filename"]))    # what we wrote, any reader reads back
    assert len(back.rows) == 8


def test_json_keys_are_the_names_as_typed(app):
    up = app.upload({"example": "huca_oviedo_hl7v23.hl7"})
    fields = [{"name": "nhc", "type": "string", "from": "PID-3.1"},
              {"name": "fecha.nacimiento", "type": "date", "from": "PID-7"},    # a dot is part of the name
              {"name": "PID-5.1", "type": "string", "from": "PID-5.1"}]
    dest = app.fields_destination({"format": "json", "fields": fields, "upload_id": up["upload_id"]})
    _, ok = accept(app, up, dest)
    first = json.loads(base64.b64decode(ok["output"]["content_b64"]))[0]
    assert first == {"nhc": "NHC-10234", "fecha.nacimiento": "1985-04-12", "PID-5.1": "FERNANDEZ ALVAREZ"}


def test_new_fields_are_proposed_by_name_and_left_out_columns_are_unmatched(app):
    up = app.upload({"example": "hospital_alvarez_buylla.csv"})
    fields = [{"name": "Apellidos", "type": "string", "from": "Apellidos"},
              {"name": "nombre", "type": "string"},                   # added by hand, no column
              {"name": "observaciones", "type": "string"}]            # nothing like it in the source
    dest = app.fields_destination({"format": "csv", "fields": fields, "upload_id": up["upload_id"]})
    prop, ok = accept(app, up, dest)
    f = prop["draft"]["fields"]
    assert f["Apellidos"]["proposed_by"] == "direct"
    assert f["nombre"]["from"] == ["Nombre"] and f["nombre"]["proposed_by"] == "rules"
    assert f["observaciones"]["from"] == []
    assert "DNI" in prop["draft"]["unmatched"]           # left out of the list: decided at approval, never lost silently
    assert "DNI" in ok["recipe"]["extras"]["drop"]
    header = base64.b64decode(ok["output"]["content_b64"]).decode("utf-8").splitlines()[0]
    assert header == "Apellidos,nombre,observaciones"


def test_list_values_stay_a_list():
    src = b'[{"id": "1", "tags": ["a", "b"]}, {"id": "2", "tags": ["c"]}]'
    rows = to_rows(parse_bytes(src, "s.json"))
    fields = {f["name"]: f for f in fields_from_rows(rows)}
    assert fields["tags"]["multiple"] == "list"
    from multibridge import matcher, recipe
    from multibridge.engine import run
    for fmt, expect in (("json", ["a", "b"]), ("csv", "a; b")):
        e = Expected.from_fields(fmt, list(fields.values()), "t")
        spec = {t.path: {"status": "mapped", "from": [f["from"]],
                         "transforms": matcher.transforms_for(rows, [f["from"]], t)[0]}
                for t, f in zip(e.targets, fields.values())}
        r = recipe.approve(recipe.new("t", rows, e, spec, "direct"), e, by="test")
        data = run(rows, r, e).write(e)
        if fmt == "json":
            assert json.loads(data)[0]["tags"] == expect
        else:
            assert data.decode().splitlines()[1] == f"1,{expect}"


def test_xml_names_become_valid_tags():
    fields = [{"name": n} for n in ("Nº Historia", "F. Nacimiento", "Peso (kg)", "1er_apellido", "a b", "a_b",
                                     "xmlns", "PID-5.1")]
    e = Expected.from_fields("xml", fields, "t")
    assert [t.leaf for t in e.targets] == ["No_Historia", "F_Nacimiento", "Peso_kg", "_1er_apellido", "a_b",
                                           "a_b_2", "_xmlns", "PID-5.1"]
    assert all(t.path == f"registro.{t.leaf}" for t in e.targets)
    item = {e.targets[0].path: "N-1", e.targets[3].path: None}
    data = formats.get("xml").write([item], e)
    assert formats.get("xml").check(data) == []
    assert b"<No_Historia>N-1</No_Historia>" in data and b"_1er_apellido" not in data   # empty: left out


def test_same_list_same_destination_id():
    a = Expected.from_fields("csv", [{"name": "x", "type": "date"}], "t")
    b = Expected.from_fields("csv", [{"name": "x", "type": "date"}], "t")
    c = Expected.from_fields("csv", [{"name": "x", "type": "string"}], "t")
    assert a.id == b.id != c.id     # an approved recipe is reused only for the same list


@pytest.mark.parametrize("fields, problem", [
    ([], "al menos un campo"),
    ([{"name": "a"}, {"name": "a"}], "repetido"),
    ([{"name": " "}], "nombre"),
    ([{"name": "a", "type": "datetime"}], "tipo desconocido"),
    ([{"name": "a", "multiple": "all"}], "multiple"),
])
def test_bad_field_lists_are_refused(app, fields, problem):
    with pytest.raises(ApiError) as e:
        app.fields_destination({"format": "json", "fields": fields})
    assert e.value.status == 400 and problem in str(e.value)


@pytest.mark.parametrize("fmt", ["fhir", "hl7v2"])
def test_standard_messages_need_an_example(app, fmt):
    with pytest.raises(ApiError) as e:
        app.fields_destination({"format": fmt, "fields": [{"name": "a"}]})
    assert e.value.status == 422


def test_editing_the_list_replaces_the_same_destination(app):
    first = app.fields_destination({"format": "json", "fields": [{"name": "a"}]})
    again = app.fields_destination({"format": "xml", "fields": [{"name": "a"}, {"name": "b"}], "replace": first["key"]})
    assert again["key"] == first["key"] and again["format"] == "xml"
    other = app.fields_destination({"format": "json", "fields": [{"name": "a"}], "replace": "cdss_paciente"})
    assert other["key"].startswith("medida-") and other["key"] != first["key"]   # only its own kind is replaced
    mine = [d for d in app.list_destinations() if d["origin"] == "medida"]
    assert len(mine) == 2


def test_a_dropped_connection_is_not_answered():
    """The browser closing a request mid-answer (reload, another page) is not an error to report."""
    class Gone(Handler):
        def __init__(self):
            self.headers = {"Host": "127.0.0.1:8766"}
            self.sent = []

        def _send(self, status, payload, content_type=None):
            self.sent.append(status)
            raise ConnectionAbortedError(10053, "aborted")

    h = Gone()
    h._guard(lambda: h._send(200, {}))
    assert h.sent == [200] and h.close_connection is True   # no second attempt with a 500
