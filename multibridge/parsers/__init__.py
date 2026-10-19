"""load(path) picks the right parser and returns a profiled Dataset."""

from __future__ import annotations

from pathlib import Path

from ..model import Dataset
from ..profile import profile_dataset
from . import csv_, excel, fhir, hl7v2


class UnsupportedFormat(ValueError):
    pass


def detect(data: bytes, name: str) -> str:
    ext = Path(name).suffix.lower()
    head = data[:64].lstrip(b"\xef\xbb\xbf\x0b \r\n\t")
    if ext in (".xlsx", ".xlsm") or data[:4] == b"PK\x03\x04":
        return "excel"
    if ext == ".xls" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise UnsupportedFormat(
            f"{name}: old binary .xls is not supported. Open it in Excel/LibreOffice and save as .xlsx."
        )
    if ext in (".hl7", ".er7") or head.startswith(b"MSH"):
        return "hl7v2"
    if ext in (".json", ".ndjson") or head[:1] in (b"{", b"["):
        return "json"
    return "csv"


def parse_bytes(data: bytes, name: str, profile: bool = True) -> Dataset:
    kind = detect(data, name)
    if kind == "excel":
        ds = excel.parse(data, name)
    elif kind == "hl7v2":
        ds = hl7v2.parse(data, name)
    elif kind == "json":
        ds = fhir.parse(data, name)
    else:
        ds = csv_.parse(data, name)
    if profile:
        profile_dataset(ds)
    return ds


def load(path: str | Path, profile: bool = True) -> Dataset:
    p = Path(path)
    return parse_bytes(p.read_bytes(), p.name, profile=profile)
