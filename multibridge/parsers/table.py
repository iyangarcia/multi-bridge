"""Find the real table(s) inside a spreadsheet-shaped grid.

Excel/CSV exports are rarely "row 1 = header". Typical mess:

    Tienda Centro - Listado de pedidos                <- title (often merged)
    Exportado: 12/03/2026 por ERP                     <- metadata
                                                      <- blank
    Cliente  | Cliente  | Envío         | Pedido      <- group header (merged cells)
    Nº socio | Nombre   | Peso (kg)     | Producto    <- real header
    ...data...
    Total pedidos: 6                                  <- footer
    Nota: datos sintéticos                            <- notes
    Código | Significado                              <- a second table on the same sheet

This module turns that into clean tables with combined labels
("Antropometría / Peso (kg)") and keeps the title/notes as human notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import column_letter

VALUE_LIKE = re.compile(
    r"^[+-]?\d+([.,]\d+)?$"            # numbers, decimal comma included
    r"|^\d{1,4}[/-]\d{1,2}[/-]\d{1,4}"  # 14/02/1978, 2026-03-12
    r"|^\d{4}-\d{2}-\d{2}"
)
FOOTER = re.compile(r"^\s*(total(es)?\b|suma\b|notas?\b|fuente\b|observaciones\b|\*)", re.I)


@dataclass
class Table:
    labels: list[str]
    columns: list[int]                 # original column indexes of the kept columns
    rows: list[list[str]]              # data, already restricted to `columns`
    header_row: int                    # 0-based row of the real header
    unnamed: set[int] = field(default_factory=set)  # positions (in labels) with no header text


def _cells(row: list[str]) -> list[str]:
    return [c for c in row if c]


def _header_shaped(row: list[str]) -> bool:
    cells = _cells(row)
    return (
        len(cells) >= 2
        and not any(VALUE_LIKE.match(c) for c in cells)
        and len({c.lower() for c in cells}) == len(cells)
        and not FOOTER.match(cells[0])
    )


def _is_header(rows: list[list[str]], j: int) -> bool:
    if not _header_shaped(rows[j]):
        return False
    following = [rows[k] for k in range(j + 1, min(j + 4, len(rows))) if _cells(rows[k])]
    if not following:
        return False
    density = len(_cells(rows[j]))
    if density < 0.5 * max(len(_cells(r)) for r in following):
        return False
    # A sparse group row sitting on top of a fuller header: let the fuller one win.
    below = rows[j + 1]
    if _header_shaped(below) and len(_cells(below)) > density:
        return False
    return True


def _group_labels(row: list[str]) -> list[str] | None:
    """A row of group names above the header, forward-filled like merged cells."""
    cells = _cells(row)
    if len(cells) < 2 or any(VALUE_LIKE.match(c) for c in cells) or len(set(cells)) < 2:
        return None
    filled, current = [], ""
    for c in row:
        current = c or current
        filled.append(current)
    return filled


def find_tables(grid: list[list[str]]) -> tuple[list[Table], list[str]]:
    """Return the tables found in `grid` plus free-text notes (titles, footers)."""
    width = max((len(r) for r in grid), default=0)
    rows = [[(c or "").strip() for c in r] + [""] * (width - len(r)) for r in grid]
    tables: list[Table] = []
    notes: list[str] = []

    i = 0
    while i < len(rows):
        h = next((j for j in range(i, len(rows)) if _is_header(rows, j)), None)
        stop = h if h is not None else len(rows)
        group = _group_labels(rows[h - 1]) if h is not None and h - 1 >= i else None
        skipped = range(i, stop - 1 if group else stop)
        notes += [" | ".join(dict.fromkeys(_cells(rows[k]))) for k in skipped if _cells(rows[k])]
        if h is None:
            break

        end = h + 1
        while end < len(rows) and _cells(rows[end]) and not FOOTER.match(_cells(rows[end])[0]):
            end += 1
        data = rows[h + 1:end]

        header = rows[h]
        keep = [c for c in range(width) if header[c] or any(r[c] for r in data)]
        labels, unnamed, seen = [], set(), {}
        for pos, c in enumerate(keep):
            label = header[c]
            if not label:
                label = f"(sin cabecera) columna {column_letter(c)}"
                unnamed.add(pos)
            elif group and group[c] and group[c] != label:
                label = f"{group[c]} / {label}"
            seen[label] = seen.get(label, 0) + 1
            labels.append(label if seen[label] == 1 else f"{label} ({seen[label]})")

        tables.append(Table(
            labels=labels,
            columns=keep,
            rows=[[r[c] for c in keep] for r in data],
            header_row=h,
            unnamed=unnamed,
        ))
        i = end
    return tables, notes


def add_tables(ds, base_name: str, grid: list[list[str]], descriptions: dict[int, str] | None = None) -> None:
    """Find tables in `grid` and add them to the Dataset as entities with one Field per column.

    `descriptions` maps an original column index to extra text (Excel comments, formulas).
    """
    from ..model import Field

    tables, notes = find_tables(grid)
    ds.notes += [f"{base_name}: {n}" for n in notes]
    if not tables:
        ds.notes.append(f"{base_name}: no se encontró ninguna tabla con cabecera.")
    for n, t in enumerate(tables, start=1):
        entity = base_name if n == 1 else f"{base_name} (tabla {n})"
        if t.header_row:
            ds.notes.append(f"{entity}: la cabecera está en la fila {t.header_row + 1}, no en la 1.")
        ds.tables[entity] = [
            {label: (v or None) for label, v in zip(t.labels, row)} for row in t.rows
        ]
        for pos, (label, col) in enumerate(zip(t.labels, t.columns)):
            ds.fields.append(Field(
                entity=entity,
                path=label,
                label=label,
                description=(descriptions or {}).get(col, ""),
                custom=pos in t.unnamed,
            ))
