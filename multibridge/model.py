"""The one shape every parser produces.

Whatever the source format (formats/: CSV, Excel, JSON, standard messages), it ends up as a
Dataset: named tables of records plus one Field per column/path. Everything
downstream (matcher, terminology, driver engine) only ever sees this.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Union

Value = Union[str, list[str], None]

_METADATA = re.compile(r"\.(system|use|type)(\.|$)")


def is_metadata(path: str) -> bool:
    """Paths that describe a neighbouring value rather than hold data:
    identifier.system, telecom.use, identifier[dni].type.coding.code..."""
    return _METADATA.search(path) is not None


@dataclass
class Field:
    entity: str                       # table it belongs to: a sheet, a segment, a resource type
    path: str                         # stable address inside the entity: "name.family", "Peso (kg)"
    label: str = ""                   # human-readable name
    description: str = ""             # from the standard, an Excel comment, an extension URL...
    custom: bool = False              # extension, private segment, unnamed/ad-hoc column
    declared_type: str | None = None  # type the format declares (formats.declared_kind reads it)

    # Filled in by profile.profile_dataset()
    dtype: str = "unknown"            # string | integer | decimal | date | datetime | boolean | code | empty
    format: str | None = None         # "dd/mm/yyyy", "decimal comma", "yyyymmdd", a code system... or "mixed"
    formats: list[str] | None = None  # when format == "mixed": every date format seen in the column
    unit: str | None = None           # "kg", "cm"... when the label or standard says so
    kind: str = "value"               # value | identifier | categorical | free_text | coded | <pack concept kind>
    sensitive: bool = False
    sensitive_reason: str | None = None
    null_ratio: float = 0.0
    distinct: int = 0
    samples: list[str] = field(default_factory=list)
    categories: list[str] | None = None
    concepts: dict | None = None      # terminology summary for columns of domain terms (packs/)

    @property
    def key(self) -> str:
        return f"{self.entity}:{self.path}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dataset:
    source: str
    format: str                                   # a format plug-in's name (formats.FORMATS)
    tables: dict[str, list[dict[str, Value]]] = field(default_factory=dict)
    fields: list[Field] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # what a human should know before mapping

    def get(self, entity: str, path: str) -> Field:
        for f in self.fields:
            if f.entity == entity and f.path == path:
                return f
        raise KeyError(f"{entity}:{path}")

    def values(self, f: Field) -> list[Value]:
        return [rec.get(f.path) for rec in self.tables.get(f.entity, [])]

    def entities(self) -> list[str]:
        return list(self.tables)
