"""One flat row per patient, whatever the source format.

This is where everything that belongs to *reading* ends: after this step the
engine only sees rows of columns, like a spreadsheet.

    HL7 v2   one row per message: PID, PV1, AL1, ZPA... side by side (PID-5.1, PV1-7.2, ZPA-3)
             repeated segments (two AL1) become a list in that column
    FHIR     one row per Patient, plus the resources that reference it (AllergyIntolerance.code.text)
    CSV/Excel one row per data row of the main table; other tables are noted, not joined

Column names are the source paths, so a recipe says exactly where a value comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Dataset, Field, Value


@dataclass
class Rows:
    source: str
    format: str
    root: str | None
    columns: dict[str, Field] = field(default_factory=dict)  # column name -> profiled source field
    rows: list[dict[str, Value]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def values(self, column: str) -> list[Value]:
        return [r.get(column) for r in self.rows]


def _root(ds: Dataset) -> str | None:
    if not ds.tables:
        return None
    if ds.format == "hl7v2" and "PID" in ds.tables:
        return "PID"
    if ds.format == "fhir" and "Patient" in ds.tables:
        return "Patient"
    width = {e: sum(1 for f in ds.fields if f.entity == e) for e in ds.tables}
    return max(ds.tables, key=lambda e: (width[e], len(ds.tables[e])))


def _column(ds: Dataset, f: Field, root: str) -> str:
    return f.path if ds.format == "hl7v2" or f.entity == root else f"{f.entity}.{f.path}"


def _add(row: dict, column: str, value: Value) -> None:
    """Collect values from several linked records into one cell (scalar, or list when more than one)."""
    if value in (None, "", []):
        return
    new = value if isinstance(value, list) else [value]
    old = row.get(column)
    merged = ([] if old is None else old if isinstance(old, list) else [old]) + new
    row[column] = merged[0] if len(merged) == 1 else merged


def _linked(ds: Dataset, root: str, rec: dict) -> dict[str, list[dict]]:
    others = {e: recs for e, recs in ds.tables.items() if e != root}
    if ds.format == "hl7v2":
        return {e: [r for r in recs if r.get("_message") == rec.get("_message")] for e, recs in others.items()}
    if ds.format == "fhir":
        ref = f"{root}/{rec.get('id')}"
        return {e: [r for r in recs if any(k.endswith(".reference") and v == ref for k, v in r.items())]
                for e, recs in others.items()}
    return {}


def to_rows(ds: Dataset) -> Rows:
    root = _root(ds)
    out = Rows(source=ds.source, format=ds.format, root=root, notes=list(ds.notes))
    if root is None:
        return out

    joined = {"hl7v2", "fhir"}
    usable = [f for f in ds.fields if not f.path.startswith("_") and (f.entity == root or ds.format in joined)]
    by_entity: dict[str, list[Field]] = {}
    for f in usable:
        by_entity.setdefault(f.entity, []).append(f)
        out.columns.setdefault(_column(ds, f, root), f)
    if ds.format not in joined:
        out.notes += [f"La tabla '{e}' no se enlaza con los registros de '{root}' (no hay clave común); se ignora."
                      for e in ds.tables if e != root]

    for rec in ds.tables[root]:
        row: dict[str, Value] = {}
        for f in by_entity.get(root, []):
            _add(row, _column(ds, f, root), rec.get(f.path))
        for entity, recs in _linked(ds, root, rec).items():
            for f in by_entity.get(entity, []):
                for r in recs:
                    _add(row, _column(ds, f, root), r.get(f.path))
        out.rows.append(row)
    return out
