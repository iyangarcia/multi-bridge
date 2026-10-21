"""EXPECTED = an example of how the destination wants the data (hackathon design, step 1).

    expected/cdss_paciente.example.json   one example output record: target fields and types
    expected/cdss_paciente.rules.json     optional overlay: what an example can't show
                                          (allowed values, required, patterns, ranges, title case...)

The target list and types come from the example. The overlay only adds constraints.
Changing either one changes `Expected.id`, so recipes approved for the old version stop
matching (design doc §5).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

TYPES = ("string", "integer", "number", "date", "boolean")
OVERLAY_KEYS = {"type", "concept", "required", "enum", "pattern", "range", "unit", "case", "multiple", "on_missing",
                "description"}


@dataclass
class Target:
    path: str                        # "paciente.fecha_nacimiento"
    type: str = "string"
    example: object = None
    description: str = ""
    concept: str | None = None       # meaning, guessed from the name unless the overlay says otherwise
    required: bool = False
    enum: list[str] | None = None
    pattern: str | None = None
    range: tuple[float, float] | None = None
    unit: str | None = None
    case: str | None = None          # "title": "PABLO MARTINEZ" -> "Pablo Martinez"
    multiple: str | None = None      # several source values: "first" | "join"; None = it's an error
    on_missing: str = "null"         # no data: "null" | "omit"

    @property
    def leaf(self) -> str:
        return self.path.rsplit(".", 1)[-1]


def _type_of(v) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return "date"
    return "string"


def targets_from_example(example: dict) -> list[Target]:
    from .concepts import concept_for_name

    out: list[Target] = []

    def walk(obj: dict, prefix: str = "") -> None:
        for k, v in obj.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".")
            else:
                out.append(Target(path=path, type=_type_of(v), example=v, concept=concept_for_name(path)))

    walk(example[0] if isinstance(example, list) else example)
    return out


@dataclass
class Expected:
    name: str
    targets: list[Target]
    fingerprint: str

    @property
    def id(self) -> str:
        return f"{self.name}#{self.fingerprint}"

    def get(self, path: str) -> Target:
        for t in self.targets:
            if t.path == path:
                return t
        raise KeyError(path)

    @classmethod
    def from_example(cls, example: dict, name: str, rules: dict | None = None) -> "Expected":
        targets = targets_from_example(example)
        known = {t.path: t for t in targets}
        for path, extra in (rules or {}).items():
            if path not in known:
                raise ValueError(f"las reglas mencionan '{path}', que no está en el ejemplo")
            unknown = set(extra) - OVERLAY_KEYS
            if unknown:
                raise ValueError(f"{path}: claves desconocidas en las reglas: {', '.join(sorted(unknown))}")
            for k, v in extra.items():
                setattr(known[path], k, tuple(v) if k == "range" else v)
        for t in targets:
            if t.type not in TYPES:
                raise ValueError(f"{t.path}: tipo desconocido {t.type!r}")
        spec = json.dumps([{k: v for k, v in asdict(t).items() if k != "example"} for t in targets],
                          sort_keys=True, ensure_ascii=False, default=list)
        return cls(name=name, targets=targets, fingerprint=hashlib.sha256(spec.encode()).hexdigest()[:8])

    @classmethod
    def load(cls, example_path: str | Path, rules_path: str | Path | None = None) -> "Expected":
        """Load an example output; picks up `<name>.rules.json` next to `<name>.example.json` automatically."""
        p = Path(example_path)
        name = p.name.removesuffix(".json").removesuffix(".example")
        if rules_path is None:
            sibling = p.with_name(f"{name}.rules.json")
            rules_path = sibling if sibling.exists() else None
        example = json.loads(p.read_text(encoding="utf-8"))
        rules = json.loads(Path(rules_path).read_text(encoding="utf-8")) if rules_path else None
        return cls.from_example(example, name=name, rules=rules)

    # -- validation of one output value -----------------------------------------------------------
    @staticmethod
    def check(t: Target, value) -> str | None:
        """Why `value` breaks the target, or None. Never echoes the value: it may be personal data."""
        if value is None:
            return "obligatorio sin valor" if t.required else None
        if t.type == "string" and not isinstance(value, str):
            return "no es texto"
        if t.type == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
            return "no es un entero"
        if t.type == "number" and not (isinstance(value, (int, float)) and not isinstance(value, bool)):
            return "no es un número"
        if t.type == "boolean" and not isinstance(value, bool):
            return "no es booleano"
        if t.type == "date":
            try:
                dt.date.fromisoformat(value)
            except (TypeError, ValueError):
                return "no es una fecha ISO (aaaa-mm-dd)"
        if t.enum is not None and value not in t.enum:
            return "valor fuera del catálogo permitido"
        if t.pattern and not re.fullmatch(t.pattern, str(value)):
            return "no cumple el formato"
        if t.range and isinstance(value, (int, float)) and not (t.range[0] <= value <= t.range[1]):
            return f"fuera del rango {t.range[0]}–{t.range[1]}"
        return None
