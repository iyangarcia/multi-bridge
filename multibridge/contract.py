"""EXPECTED: the contract describing the data the destination application wants.

A contract is versioned JSON (see contracts/). Each target field states its
type, meaning (concept), constraints and what to do when there is no data.
Drivers are tied to one exact contract version (design doc §5).

`from_example()` drafts a contract from a sample output JSON, the hackathon idea
"show it an example of how you want the data". A human then completes the
semantics (concepts, enums, required) before using it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

TYPES = ("string", "integer", "number", "date", "boolean")


@dataclass
class TargetField:
    path: str                          # dotted path in the output: "paciente.fecha_nacimiento"
    type: str = "string"
    description: str = ""
    concept: str | None = None         # key in concepts.CONCEPTS, used by the matcher
    required: bool = False             # a record without it is rejected; the plan can't be approved without a source
    enum: list[str] | None = None      # allowed values
    pattern: str | None = None         # regex the final value must match
    range: tuple[float, float] | None = None
    unit: str | None = None
    case: str | None = None            # "title": names are delivered as "Pablo Martinez"
    multiple: str = "first"            # several source values: "first" | "join"
    on_missing: str = "null"           # no data: "null" | "omit"

    def __post_init__(self):
        if self.type not in TYPES:
            raise ValueError(f"{self.path}: unknown type {self.type!r}")
        if self.range is not None:
            self.range = tuple(self.range)

    @property
    def leaf(self) -> str:
        return self.path.rsplit(".", 1)[-1]


@dataclass
class Contract:
    name: str
    version: int
    description: str = ""
    fields: list[TargetField] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.name}@v{self.version}"

    def get(self, path: str) -> TargetField:
        for f in self.fields:
            if f.path == path:
                return f
        raise KeyError(path)

    def to_dict(self) -> dict:
        d = asdict(self)
        for f in d["fields"]:
            for k in [k for k, v in f.items() if v is None or (k == "multiple" and v == "first")
                      or (k == "on_missing" and v == "null") or (k == "required" and not v)]:
                del f[k]
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict) -> "Contract":
        return cls(name=d["name"], version=int(d["version"]), description=d.get("description", ""),
                   fields=[TargetField(**f) for f in d["fields"]])

    @classmethod
    def load(cls, path: str | Path) -> "Contract":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- validation of one output value --------------------------------------------------------
    def check(self, f: TargetField, value) -> str | None:
        """Return why `value` breaks the contract, or None. Never echoes the value (it may be personal data)."""
        if value is None:
            return "obligatorio sin valor" if f.required else None
        if f.type == "string" and not isinstance(value, str):
            return "no es texto"
        if f.type == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
            return "no es un entero"
        if f.type == "number" and not (isinstance(value, (int, float)) and not isinstance(value, bool)):
            return "no es un número"
        if f.type == "boolean" and not isinstance(value, bool):
            return "no es booleano"
        if f.type == "date":
            try:
                dt.date.fromisoformat(value)
            except (TypeError, ValueError):
                return "no es una fecha ISO (aaaa-mm-dd)"
        if f.enum is not None and value not in f.enum:
            return "valor fuera del catálogo permitido"
        if f.pattern and not re.fullmatch(f.pattern, str(value)):
            return "no cumple el formato"
        if f.range and isinstance(value, (int, float)) and not (f.range[0] <= value <= f.range[1]):
            return f"fuera del rango {f.range[0]}–{f.range[1]}"
        return None


def from_example(example: dict, name: str = "contrato", version: int = 1) -> Contract:
    """Draft a contract from one example output. Types come from the values; meaning is guessed by the matcher."""
    from .concepts import concept_for_name

    fields: list[TargetField] = []

    def walk(obj, prefix=""):
        for k, v in obj.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".")
                continue
            if isinstance(v, bool):
                typ = "boolean"
            elif isinstance(v, int):
                typ = "integer"
            elif isinstance(v, float):
                typ = "number"
            elif isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                typ = "date"
            else:
                typ = "string"
            fields.append(TargetField(path=path, type=typ, concept=concept_for_name(path),
                                      description=f"(borrador) ejemplo: {v!r}"))

    walk(example)
    return Contract(name=name, version=version,
                    description="Borrador generado desde un ejemplo: revisar conceptos, obligatorios y catálogos",
                    fields=fields)
