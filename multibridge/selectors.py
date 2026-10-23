"""Selector columns: pick a repetition or a row by its code.

Data often repeats one structure and says what each copy is with a code. The format plug-in
(formats/) declares where:

    keyed_entities   a table with one record per item and a code field saying what each is
                     ("measurements": code + value + unit)
    keyed_fields     a repeated field whose repetitions carry their own type code
                     (two identifiers in one field, each with its type)

For each such case, to_rows() adds extra columns that select by code, named
`<column> [<code column>=<code>]`, for example `value [code=8302-2]`.

They are ordinary columns from then on: the proposer scores them, a recipe names them, the engine
reads them. A recipe using one is only reusable where the same code exists. Selection happens
per repetition / segment / resource, where alignment is exact, never on flattened lists.
"""

from __future__ import annotations

import re

from .model import Dataset, Field

MAX_CODES = 20
PICKED = re.compile(r" \[[^\]=]+=[^\]]+\]$")


def is_selector(column: str) -> bool:
    return PICKED.search(column) is not None


def _as_list(v) -> list:
    return v if isinstance(v, list) else [] if v in (None, "") else [v]


def _cell(values: list):
    values = [v for v in values if v not in (None, "")]
    return None if not values else values[0] if len(values) == 1 else values


def _describe(base: Field, key: str, code: str, meanings: dict[str, str]) -> str:
    meaning = meanings.get(code)
    return f"{base.description} — solo donde {key} = {code}" + (f" ({meaning})" if meaning else "")


def build(ds: Dataset, fmt, root: str, root_records: list[dict], linked: list[dict[str, list[dict]]],
          column_of, meanings: dict[str, str]) -> list[tuple[str, Field, list, str | None]]:
    """(column name, field, value per row, unit column) for every selector worth adding.
    `meanings`: words for the codes, from the format and the domain packs."""
    by_key = {(f.entity, f.path): f for f in ds.fields}
    out = []

    for entity, (key, value_paths) in fmt.keyed_entities.items():
        if entity == root or entity not in ds.tables or (entity, key) not in by_key:
            continue
        codes = sorted({c for r in ds.tables[entity] for c in _as_list(r.get(key))})
        if not codes or len(codes) > MAX_CODES:
            continue
        key_col = column_of(by_key[(entity, key)])
        for path in value_paths:
            base = by_key.get((entity, path))
            if base is None:
                continue
            for code in codes:
                per_row = [_cell([v for r in links.get(entity, []) if code in _as_list(r.get(key))
                                  for v in _as_list(r.get(path))]) for links in linked]
                unit_path = fmt.unit_of.get(path)
                unit_col = f"{column_of(by_key[(entity, unit_path)])} [{key_col}={code}]" \
                    if unit_path and (entity, unit_path) in by_key else None
                out.append((f"{column_of(base)} [{key_col}={code}]", _field(base, key_col, code, meanings),
                            per_row, unit_col))

    # Repeated fields, kept whole per repetition by the reader (record["_reps"][field] = [{component: value}])
    for field_id, (segment, key_comp, data_comps) in fmt.keyed_fields.items():
        if segment != root:
            continue
        reps_per_row = [rec.get("_reps", {}).get(field_id, []) for rec in root_records]
        codes = sorted({rep[key_comp] for reps in reps_per_row for rep in reps if key_comp in rep})
        if not codes or len(codes) > MAX_CODES:
            continue
        comps = sorted({c for reps in reps_per_row for rep in reps for c in rep if c in data_comps})
        key_col = f"{field_id}.{key_comp}"
        for comp in comps:
            base = by_key.get((segment, f"{field_id}.{comp}"))
            if base is None:
                continue
            for code in codes:
                per_row = [_cell([rep[comp] for rep in reps if rep.get(key_comp) == code and comp in rep])
                           for reps in reps_per_row]
                out.append((f"{base.path} [{key_col}={code}]", _field(base, key_col, code, meanings),
                            per_row, None))
    return out


def _field(base: Field, key_col: str, code: str, meanings: dict[str, str]) -> Field:
    return Field(entity=base.entity, path=f"{base.path} [{key_col}={code}]", label=f"{base.label} [{key_col}={code}]",
                 description=_describe(base, key_col, code, meanings), custom=base.custom,
                 declared_type=base.declared_type)
