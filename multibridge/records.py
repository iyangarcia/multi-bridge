"""One flat row per record, whatever the source format.

This is where everything that belongs to *reading* ends: after this step the
engine only sees rows of columns, like a spreadsheet.

What one record is comes from the format plug-in (formats/): its root table, the records of
other tables linked to each root record, and the column names. For example, a message format
gives one row per message with its segments side by side; CSV/Excel give one row per data row
of the main table, and other tables are noted, not joined.

Repeated values (two linked records with the same field) become a list in that column.
Column names are the source paths, so a recipe says exactly where a value comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import formats, selectors
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


def _add(row: dict, column: str, value: Value) -> None:
    """Collect values from several linked records into one cell (scalar, or list when more than one)."""
    if value in (None, "", []):
        return
    new = value if isinstance(value, list) else [value]
    old = row.get(column)
    merged = ([] if old is None else old if isinstance(old, list) else [old]) + new
    row[column] = merged[0] if len(merged) == 1 else merged


def to_rows(ds: Dataset, packs=None) -> Rows:
    """`packs`: whose detectors profile the selector columns (default: every installed one)."""
    fmt = formats.get(ds.format)
    root = fmt.root(ds)
    out = Rows(source=ds.source, format=ds.format, root=root, notes=list(ds.notes))
    if root is None:
        return out

    def column(f: Field) -> str:
        return fmt.column(ds, f, root)

    usable = [f for f in ds.fields if not f.path.startswith("_") and (f.entity == root or fmt.joins)]
    by_entity: dict[str, list[Field]] = {}
    for f in usable:
        by_entity.setdefault(f.entity, []).append(f)
        out.columns.setdefault(column(f), f)
    if not fmt.joins:
        out.notes += [f"La tabla '{e}' no se enlaza con los registros de '{root}' (no hay clave común); se ignora."
                      for e in ds.tables if e != root]

    linked_per_row = []
    for rec in ds.tables[root]:
        row: dict[str, Value] = {}
        for f in by_entity.get(root, []):
            _add(row, column(f), rec.get(f.path))
        links = fmt.linked(ds, root, rec)
        linked_per_row.append(links)
        for entity, recs in links.items():
            for f in by_entity.get(entity, []):
                for r in recs:
                    _add(row, column(f), r.get(f.path))
        out.rows.append(row)
    if fmt.joins:
        _add_selectors(ds, out, fmt, root, linked_per_row, column, packs)
    return out


def _add_selectors(ds: Dataset, out: Rows, fmt, root: str, linked_per_row: list, column, packs) -> None:
    """Columns that pick a repetition or a row by its code (see selectors.py)."""
    from . import packs as registry
    from .profile import UNITS, profile_field

    packs = registry.installed() if packs is None else list(packs)
    meanings = {**fmt.code_meanings, **{k: v for p in packs for k, v in p.code_meanings.items()}}
    built = selectors.build(ds, fmt, root, ds.tables[root], linked_per_row, column, meanings)
    values_of = {name: per_row for name, _, per_row, _ in built}
    for name, f, per_row, unit_col in built:
        if all(v is None for v in per_row):
            continue
        base_name = name.rsplit(" [", 1)[0]
        if base_name in out.columns and per_row == [r.get(base_name) for r in out.rows]:
            continue   # selects nothing the base column doesn't already give
        profile_field(f, per_row, packs=packs)
        units = {v for v in values_of.get(unit_col) or [] if v is not None}
        if not f.unit and len(units) == 1 and str(next(iter(units))).lower() in UNITS:
            f.unit = str(next(iter(units))).lower()
        out.columns[name] = f
        for row, v in zip(out.rows, per_row):
            if v is not None:
                row[name] = v
