"""Format plug-ins: one per data format, never one per pair of formats.

A plug-in knows a format's *structure*, nothing about what the data means (that is a domain pack):

    read(data, name)     bytes -> Dataset (tables of records + one Field per column/path)
    destination(...)     an example in this format -> Destination: target fields + a template
    blank(fields, ...)   a plain field list -> Destination, for formats whose shape needs no example
    write(items, exp)    output items (output.py) -> bytes in this format, shaped like the example
    check(data)          problems that make `data` invalid in this format ([] = valid)

    root / linked / column        what one record is and which other records belong to it
                                  (to_rows builds one flat row per record from these)
    keyed_entities / keyed_fields repeated structures whose copies a code tells apart
                                  (selector columns, see selectors.py)
    timestamp_types / coded_types declared types that say how to read a value
    code_meanings                 words for the codes the format itself defines

Adding a format = one module here plus one entry in FORMATS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..model import Dataset, Field


class UnsupportedFormat(ValueError):
    pass


@dataclass
class Destination:
    """What a format plug-in reads from an example of the output."""
    format: str
    targets: list                                  # expected.Target
    template: object = None                        # whatever the writer needs to shape the output
    constants: dict = field(default_factory=dict)  # fixed values written as in the example (path -> value)


class Format:
    name = ""
    label = ""
    extensions: tuple[str, ...] = ()
    mime = "application/octet-stream"
    joins = False                       # linked tables are joined into the root record's row
    keyed_entities: dict[str, tuple[str, list[str]]] = {}
    keyed_fields: dict[str, tuple[str, int, list[int]]] = {}
    unit_of: dict[str, str | None] = {}
    code_meanings: dict[str, str] = {}
    timestamp_types: set[str] = set()
    coded_types: set[str] = set()

    def sniff(self, data: bytes, name: str) -> bool:
        return Path(name).suffix.lower() in self.extensions

    def read(self, data: bytes, name: str) -> Dataset:
        raise NotImplementedError(f"{self.label}: no reader yet")

    def destination(self, data: bytes, name: str, pack, options: dict) -> Destination:
        raise UnsupportedFormat(f"{self.label}: todavía no puede usarse como destino")

    def blank(self, fields: list[dict], options: dict) -> Destination:
        """A destination from a plain field list, no example: [{"name", "type", "required", "multiple"}].
        One target per field, in order. Formats that need an example to know their shape don't have it."""
        raise UnsupportedFormat(f"{self.label}: necesita un ejemplo de la salida")

    @property
    def can_blank(self) -> bool:
        return type(self).blank is not Format.blank

    def write(self, items: list[dict], expected) -> bytes:
        raise NotImplementedError(f"{self.label}: no writer yet")

    def check(self, data: bytes) -> list[str]:
        raise NotImplementedError(f"{self.label}: no checker yet")

    @property
    def extension(self) -> str:
        return self.extensions[0] if self.extensions else ""

    def root(self, ds: Dataset) -> str | None:
        """The table whose records become rows: by default the widest one."""
        if not ds.tables:
            return None
        width = {e: sum(1 for f in ds.fields if f.entity == e) for e in ds.tables}
        return max(ds.tables, key=lambda e: (width[e], len(ds.tables[e])))

    def linked(self, ds: Dataset, root: str, rec: dict) -> dict[str, list[dict]]:
        """Records of other tables that belong to this root record. None by default."""
        return {}

    def column(self, ds: Dataset, f: Field, root: str) -> str:
        return f.path if f.entity == root else f"{f.entity}.{f.path}"


def json_bytes(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


from . import hl7v2, json_, tabular, xml_  # noqa: E402  (the plug-ins subclass Format)

# Detection order matters: binary signatures first, plain text (CSV) last.
FORMATS: dict[str, Format] = {f.name: f for f in (tabular.EXCEL, hl7v2.HL7V2, json_.JSON, json_.FHIR, xml_.XML,
                                                  tabular.CSV)}
DETECT = [tabular.EXCEL, hl7v2.HL7V2, json_.JSON, xml_.XML]
FALLBACK = tabular.CSV


def get(name: str) -> Format:
    try:
        return FORMATS[name]
    except KeyError:
        raise UnsupportedFormat(f"formato desconocido: {name}") from None


def detect(data: bytes, name: str) -> Format:
    if tabular.EXCEL.sniff(data, name):
        return tabular.EXCEL
    if Path(name).suffix.lower() == ".xls" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise UnsupportedFormat(
            f"{name}: old binary .xls is not supported. Open it in Excel/LibreOffice and save as .xlsx."
        )
    return next((f for f in DETECT if f.sniff(data, name)), FALLBACK)


def destination(data: bytes, name: str, pack, options: dict | None = None) -> Destination:
    """Read an example of the output with its format's plug-in."""
    return detect(data, name).destination(data, name, pack, options or {})


def declared_kind(declared: str | None) -> str | None:
    """"timestamp" or "coded" when some format declares that type, else None."""
    if declared is None:
        return None
    if any(declared in f.timestamp_types for f in FORMATS.values()):
        return "timestamp"
    if any(declared in f.coded_types for f in FORMATS.values()):
        return "coded"
    return None
