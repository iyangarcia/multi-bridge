"""The one shape every parser produces.

Whatever the source (HL7 v2, FHIR, CSV, a hand-made Excel), it ends up as a
Dataset: named tables of records plus one Field per column/path. Everything
downstream (matcher, terminology, driver engine) only ever sees this.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Union

Value = Union[str, list[str], None]


@dataclass
class Field:
    entity: str                       # table it belongs to: "PID", "Patient", "Ingresos"
    path: str                         # stable address inside the entity: "PID-5.1", "name.family", "Peso (kg)"
    label: str = ""                   # human-readable name
    description: str = ""             # from the standard, an Excel comment, an extension URL...
    custom: bool = False              # Z-segment, FHIR extension, unnamed/ad-hoc column
    declared_type: str | None = None  # type the standard declares (HL7 "TS", ...)

    # Filled in by profile.profile_dataset()
    dtype: str = "unknown"            # string | integer | decimal | date | datetime | boolean | code | empty
    format: str | None = None         # "dd/mm/yyyy", "decimal comma", "yyyymmdd", "ICD-10"...
    unit: str | None = None           # "kg", "cm"... when the label or standard says so
    kind: str = "value"               # value | identifier | categorical | free_text | coded | clinical_concept
    sensitive: bool = False
    sensitive_reason: str | None = None
    null_ratio: float = 0.0
    distinct: int = 0
    samples: list[str] = field(default_factory=list)
    categories: list[str] | None = None
    concepts: dict | None = None      # terminology summary for clinical text columns

    @property
    def key(self) -> str:
        return f"{self.entity}:{self.path}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dataset:
    source: str
    format: str                                   # "csv" | "excel" | "fhir" | "json" | "hl7v2"
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
