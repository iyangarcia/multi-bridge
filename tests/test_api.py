"""The local API behind the web app: a real server on a random port, over a temporary copy of the project."""

import base64
import http.client
import json
import shutil
import threading
from pathlib import Path

import pytest

from multibridge.api import make_server

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("mb")
    for folder in ("web", "expected", "examples"):
        shutil.copytree(ROOT / folder, root / folder)
    srv = make_server(root, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, root
    srv.shutdown()
    srv.server_close()


def call(server, method, path, body=None, host=None, raw=False):
    srv, _ = server
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
    headers = {"Host": host or f"127.0.0.1:{srv.server_address[1]}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, (payload if raw else json.loads(payload or b"null"))


def test_listens_on_loopback_only(server):
    srv, _ = server
    assert srv.server_address[0] == "127.0.0.1"


def test_rejects_foreign_host_header(server):
    """DNS rebinding: a page on another domain pointed at 127.0.0.1 must not be able to use the API."""
    status, body = call(server, "GET", "/api/expected", host="attacker.example.com")
    assert status == 403


def test_static_files_and_no_path_traversal(server):
    status, page = call(server, "GET", "/", raw=True)
    assert status == 200 and b"MULTI <b>BRIDGE</b>" in page
    for bad in ("/../expected/cdss_paciente.rules.json", "/%2e%2e/expected/cdss_paciente.rules.json",
                "/..%5cexpected%5ccdss_paciente.rules.json"):
        assert call(server, "GET", bad, raw=True)[0] == 404


def test_full_flow_propose_approve_reuse(server):
    _, root = server
    status, up = call(server, "POST", "/api/upload", {"example": "huca_oviedo_hl7v23.hl7"})
    assert status == 200 and up["format"] == "hl7v2" and up["rows"] == 8
    status, prop = call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "rules"})
    assert status == 200 and prop["reusable"] is None
    assert prop["previews"]["paciente.nombre"] == {"before": "LUCIA", "after": "Lucia", "problem": None}

    decisions = {"fields": {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]}
                            for t, f in prop["draft"]["fields"].items()}}
    status, ok = call(server, "POST", "/api/approve", {"upload_id": up["upload_id"], "draft": decisions, "by": "Ana"})
    golden = json.loads((ROOT / "tests" / "golden" / "output" / "huca_oviedo_hl7v23.json").read_text(encoding="utf-8"))
    assert status == 200 and ok["records"] == golden and ok["report"]["rejected"] == 0
    assert (root / "recipes" / "huca_oviedo_hl7v23.json").is_file()

    status, prop2 = call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "rules"})
    assert prop2["reusable"]["name"] == "huca_oviedo_hl7v23" and prop2["reusable"]["approved_by"] == "Ana"
    status, again = call(server, "POST", "/api/run", {"upload_id": up["upload_id"], "recipe": "huca_oviedo_hl7v23"})
    assert status == 200 and again["records"] == golden
    status, listed = call(server, "GET", "/api/recipes")
    assert [r["name"] for r in listed] == ["huca_oviedo_hl7v23"]


def test_browser_cannot_rewrite_provenance(server):
    """The approved recipe's 'proposal' comes from the server's copy, so changed_by can't be hidden."""
    _, up = call(server, "POST", "/api/upload", {"example": "hospital_alvarez_buylla.csv"})
    _, prop = call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "rules"})
    fields = {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]}
              for t, f in prop["draft"]["fields"].items()}
    fields["datos_clinicos.alergia"] = {"status": "no_data", "from": [], "transforms": []}
    forged = {"fields": {t: {**f, "proposal": f, "proposed_by": "nadie"} for t, f in fields.items()}}
    status, ok = call(server, "POST", "/api/approve", {"upload_id": up["upload_id"], "draft": forged, "by": "Ana"})
    alergia = ok["recipe"]["fields"]["datos_clinicos.alergia"]
    assert alergia["changed_by"] == "Ana" and alergia["proposed_by"] == "rules"
    assert ok["recipe"]["source"]["signature"] and ["Alergias", "string"] not in ok["recipe"]["source"]["signature"]


def test_approval_needs_a_name_and_no_pending(server):
    _, up = call(server, "POST", "/api/upload", {"example": "hospital_leon_fhir.json"})
    _, prop = call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "rules"})
    fields = {t: {"status": f["status"], "from": f["from"], "transforms": f["transforms"]}
              for t, f in prop["draft"]["fields"].items()}
    assert call(server, "POST", "/api/approve", {"upload_id": up["upload_id"], "draft": {"fields": fields}, "by": ""})[0] == 409
    fields["paciente.id"] = {"status": "pending", "from": [], "transforms": []}
    status, err = call(server, "POST", "/api/approve", {"upload_id": up["upload_id"], "draft": {"fields": fields}, "by": "Ana"})
    assert status == 409 and "paciente.id" in err["error"]


def test_changing_a_column_returns_new_transforms_and_preview(server):
    _, up = call(server, "POST", "/api/upload", {"example": "hospital_alvarez_buylla.csv"})
    status, f = call(server, "POST", "/api/field", {"upload_id": up["upload_id"], "target": "paciente.fecha_nacimiento",
                                                    "from": ["F. Nacimiento"]})
    assert status == 200 and f["transforms"] == [{"op": "date", "from": "%d/%m/%Y"}]
    assert f["preview"]["after"] == "1978-02-14"
    status, f = call(server, "POST", "/api/field", {"upload_id": up["upload_id"], "target": "paciente.fecha_nacimiento",
                                                    "from": ["Sexo"]})
    assert f["preview"]["problem"]                      # "M" is not a date: shown before approving
    assert call(server, "POST", "/api/field", {"upload_id": up["upload_id"], "target": "paciente.id",
                                               "from": ["No existe"]})[0] == 400


def test_uploaded_file_and_ai_view(server):
    raw = "NHC;Nombre;DNI\nX1;Ana;12345678Z\n".encode()
    status, up = call(server, "POST", "/api/upload", {"name": "mini.csv", "content_b64": base64.b64encode(raw).decode()})
    assert status == 200 and up["rows"] == 1
    assert "12345678Z" not in json.dumps(up["ai_view"])        # the model's view is masked
    assert up["samples"]["DNI"] == ["12345678Z"]               # the reviewer sees it, on this machine
    assert call(server, "POST", "/api/upload", {"name": "x.csv", "content_b64": "%%%"})[0] == 400


def test_unknown_upload_and_model(server):
    assert call(server, "POST", "/api/propose", {"upload_id": "nope", "model": "rules"})[0] == 404
    _, up = call(server, "POST", "/api/upload", {"example": "hospital_alvarez_buylla.csv"})
    assert call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "gpt-cloud"})[0] == 400


def test_proposal_says_what_each_confidence_meant_in_tests(server):
    """Phase 9: next to each confidence, the hit rate measured on the generated evaluation set."""
    from multibridge import calibration
    status, up = call(server, "POST", "/api/upload", {"example": "huca_oviedo_hl7v23.hl7"})
    status, prop = call(server, "POST", "/api/propose", {"upload_id": up["upload_id"], "model": "rules"})
    assert status == 200
    for t, f in prop["draft"]["fields"].items():
        assert prop["measured"][t] == calibration.measured(f["confidence"], "rules")
    assert any(m and 0 < m["rate"] <= 1 and m["n"] > 0 for m in prop["measured"].values())
    assert all("measured" in o for options in prop["ranking"].values() for o in options)
