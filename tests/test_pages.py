"""The GitHub Pages demo (phase 10): the API answering inside the browser, and what the build ships."""

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from multibridge import browser

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts" / "build_pages.py")
build_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_pages)


@pytest.fixture
def app(tmp_path):
    for folder in ("expected", "examples"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    browser.start(str(tmp_path))
    return tmp_path


def call(method, url, body=None):
    return json.loads(browser.call(method, url, None if body is None else json.dumps(body)))


def test_browser_flow_is_the_servers(app):
    health = call("GET", "/api/health")["data"]
    assert health["browser"] is True and not any(health["ollama"].values())
    up = call("POST", "/api/upload", {"example": "huca_oviedo_hl7v23.hl7"})
    assert up["status"] == 200 and not up["saved"]
    uid = up["data"]["upload_id"]
    p = call("POST", "/api/propose", {"upload_id": uid, "model": "rules"})["data"]
    decisions = {k: {"status": "mapped" if f["status"] == "pending" else f["status"], "from": f["from"],
                     "transforms": f["transforms"]} for k, f in p["draft"]["fields"].items()}
    ok = call("POST", "/api/approve", {"upload_id": uid, "draft": {"fields": decisions}, "by": "test"})
    assert ok["status"] == 200 and ok["saved"]   # the worker copies recipes/ to IndexedDB after this
    assert (app / "recipes" / "huca_oviedo_hl7v23.json").is_file()
    assert [r["name"] for r in call("GET", "/api/recipes")["data"]] == ["huca_oviedo_hl7v23"]


def test_browser_has_no_ai_and_reports_errors_as_text(app):
    up = call("POST", "/api/upload", {"example": "huca_oviedo_hl7v23.hl7"})["data"]
    ai = call("POST", "/api/propose", {"upload_id": up["upload_id"], "model": "qwen3:8b"})
    assert ai["status"] == 503 and "instalación local" in ai["error"]
    assert call("POST", "/api/propose", {"upload_id": up["upload_id"], "model": "auto"})["status"] == 200
    assert call("GET", "/api/nothing")["status"] == 404
    assert json.loads(browser.call("POST", "/api/upload", "{not json"))["status"] == 400
    assert call("POST", "/api/upload", {"name": "x.csv", "content_b64": "%%"})["error"] == "contenido no válido"


def test_build_ships_no_recipes_or_saved_lists(tmp_path):
    names = [n for n, _ in build_pages.package_files(tmp_path)]
    assert "multibridge/browser.py" in names and "expected/cdss_paciente.example.json" in names
    assert not [n for n in names if n.startswith("recipes/") or n.endswith(".fields.json")]
    assert not [n for n in names if n.endswith(".py") and n.startswith("examples/")]   # builders stay out
    assert not [n for n in names if "__pycache__" in n]


def test_build_switch_and_pyodide_version_match():
    comun = (ROOT / "web" / "js" / "comun.js").read_text(encoding="utf-8")
    assert comun.count(build_pages.FLAG) == 1
    worker = (ROOT / "web" / "js" / "navegador.js").read_text(encoding="utf-8")
    assert re.search(r"pyodide/v0\.29\.5/full/", worker)   # Python 3.13; change both together
    assert build_pages.PYODIDE_PYTHON == (3, 13)


def test_precompiled_files_load(tmp_path):
    src = tmp_path / "pkg" / "hola.py"
    src.parent.mkdir()
    src.write_text("X = 41 + 1\n", encoding="utf-8")
    files = build_pages.compiled([("pkg/hola.py", src)], tmp_path)
    if sys.version_info[:2] != build_pages.PYODIDE_PYTHON:
        assert files == [("pkg/hola.py", src)]
        return
    (name, pyc), = [f for f in files if f[0].endswith(".pyc")]
    assert name == f"pkg/__pycache__/hola.{sys.implementation.cache_tag}.pyc"
    data = build_pages.zip_bytes(files)
    assert data == build_pages.zip_bytes(files)   # same bytes, same name
