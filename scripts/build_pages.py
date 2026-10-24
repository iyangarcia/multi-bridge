"""Build the GitHub Pages demo: the web app with the Python running in the visitor's browser (Pyodide).

    python scripts/build_pages.py            # -> site/
    python -m http.server -d site 8000       # try it: http://localhost:8000

What goes in:
- web/ as it is, with MODO_NAVEGADOR switched on in js/comun.js;
- demo/multibridge-<hash>.zip: the multibridge package, openpyxl and et_xmlfile (unpacked from their
  wheels, so the browser fetches nothing from PyPI), the synthetic examples and the example
  destinations. No recipes and no saved field lists: those are the user's, and in the demo each
  visitor makes their own (kept in their browser);
- demo/manifest.json: which zip to load (its name changes when its content does).
The Python files go precompiled (a .pyc for each .py) when this runs on the Python version Pyodide
has: compiling in the browser took about 3 seconds on every page. Synthetic data only (C1):
everything here is already in the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAG = "const MODO_NAVEGADOR = false;"
WORKER = 'new Worker("js/navegador.js")'
DICTIONARY = 'fetch("i18n/en.json")'
WHEELS = ("openpyxl", "et_xmlfile")
PYODIDE_PYTHON = (3, 13)   # Pyodide 0.29.5, the version web/js/navegador.js loads


def package_files(wheels: Path) -> list[tuple[str, Path]]:
    """(path inside the zip, file) for everything the browser needs to run the API."""
    out = [(p.relative_to(ROOT).as_posix(), p) for p in sorted((ROOT / "multibridge").rglob("*"))
           if p.is_file() and "__pycache__" not in p.parts]
    out += [(p.relative_to(ROOT).as_posix(), p) for p in sorted((ROOT / "examples").rglob("*"))
            if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts
            and not p.name.startswith("~$")]   # Excel's lock file while a workbook is open
    out += [(p.relative_to(ROOT).as_posix(), p) for p in sorted((ROOT / "expected").iterdir())
            if p.is_file() and (".example." in p.name or p.name.endswith(".rules.json"))]
    out += [(p.relative_to(wheels).as_posix(), p) for p in sorted(wheels.rglob("*")) if p.is_file()]
    return out


def unpack_wheels(dest: Path) -> None:
    """openpyxl and et_xmlfile at the versions the tests run with, unpacked as in site-packages."""
    download = dest.parent / "download"
    pins = [f"{name}=={version(name)}" for name in WHEELS]
    subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--disable-pip-version-check", "--no-deps",
                    "--only-binary=:all:", "--dest", str(download), *pins], check=True)
    found = sorted(download.glob("*.whl"))
    if len(found) != len(WHEELS):
        raise SystemExit(f"expected {len(WHEELS)} wheels, got {[w.name for w in found]}")
    for w in found:
        with zipfile.ZipFile(w) as z:
            z.extractall(dest)


def compiled(files: list[tuple[str, Path]], work: Path) -> list[tuple[str, Path]]:
    """Each .py with its .pyc in __pycache__, never checked against the source (the zip is rebuilt
    whenever a source changes). Skipped on another Python version: its bytecode would not load."""
    if sys.version_info[:2] != PYODIDE_PYTHON:
        print(f"warning: Python {sys.version_info[0]}.{sys.version_info[1]} is not Pyodide's "
              f"{PYODIDE_PYTHON[0]}.{PYODIDE_PYTHON[1]}: no precompiled files, the demo starts ~3 s slower")
        return files
    out = list(files)
    for name, path in files:
        if name.endswith(".py"):
            pyc = work / "pyc" / f"{name}c"
            py_compile.compile(str(path), cfile=str(pyc), dfile=name, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            folder, _, stem = name[:-3].rpartition("/")
            out.append((f"{folder}/__pycache__/{stem}.{sys.implementation.cache_tag}.pyc".lstrip("/"), pyc))
    return out


def zip_bytes(files: list[tuple[str, Path]]) -> bytes:
    """The same bytes for the same files (fixed timestamps), so the name only changes with the content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in sorted(files):
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), path.read_bytes(),
                       compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def stamp(out: Path) -> str:
    """?v=<hash of the site> on every stylesheet and script, the worker and the dictionary: Pages lets browsers
    cache files for 10 minutes, and a new page with an old script breaks."""
    digest = hashlib.sha256()
    for p in sorted(out.rglob("*")):
        if p.is_file():
            digest.update(p.relative_to(out).as_posix().encode() + b"\0" + p.read_bytes())
    v = digest.hexdigest()[:10]
    for page in out.glob("*.html"):
        text = re.sub(r'((?:href|src)="(?:css|js)/[\w-]+\.(?:css|js))"', rf'\1?v={v}"', page.read_text(encoding="utf-8"))
        page.write_text(text, encoding="utf-8", newline="")
    comun = out / "js" / "comun.js"
    text = comun.read_text(encoding="utf-8")
    for fixed in (WORKER, DICTIONARY):
        if text.count(fixed) != 1:
            raise SystemExit(f"js/comun.js no longer has {fixed!r}: update scripts/build_pages.py")
        text = text.replace(fixed, fixed.replace('")', f'?v={v}")'))
    comun.write_text(text, encoding="utf-8", newline="")
    return v


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    comun = out / "js" / "comun.js"
    text = comun.read_text(encoding="utf-8")
    if FLAG not in text:
        raise SystemExit(f"js/comun.js no longer has {FLAG!r}: update scripts/build_pages.py")
    comun.write_text(text.replace(FLAG, FLAG.replace("false", "true")), encoding="utf-8", newline="")
    stamp(out)
    (out / ".nojekyll").write_text("")   # serve files as they are (no Jekyll processing on Pages)

    demo = out / "demo"
    demo.mkdir()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        unpack_wheels(work / "wheels")
        data = zip_bytes(compiled(package_files(work / "wheels"), work))
    package = f"multibridge-{hashlib.sha256(data).hexdigest()[:10]}.zip"
    (demo / package).write_bytes(data)
    manifest = {"package": package}
    (demo / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "site")
    print(json.dumps(build(ap.parse_args().out), indent=2))


if __name__ == "__main__":
    main()
