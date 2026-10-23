"""EXPECTED = an example of how the destination wants the data (hackathon design, step 1).

    expected/<name>.example.<ext>   one example of the output, in the destination's own format
                                    (JSON, CSV, Excel, XML, standard messages...): fields, types, shape
    expected/<name>.rules.json      optional overlay: what an example can't show
                                    (allowed values, required, patterns, ranges, title case...)

The example goes through its format plug-in (formats/), which lists the target fields and keeps
the example as a *template* for its writer: the output looks like the example (same nesting,
same date and decimal style, same fixed values). The overlay only adds constraints, plus a few
keys for the whole destination:

    "$pack"            the domain pack its fields belong to (packs/)
    "$group_by"        a target path: rows with the same value become one output item, and the
                       targets inside a repeated group ("pedido.lineas[].producto") collect one
                       entry per row (many rows -> one item)
    "$repeat"          paths of elements the example shows once but that repeat (XML)
    "$fixed" / "$targets"  demote a target to a fixed value of the template, or the reverse
    "$extension_base"  base URL for custom fields carried into a standard format (as extensions)

A destination can also come with no example: a format plus a plain list of fields
(`Expected.from_fields`), typed by hand or taken from every column of a source (`fields_from_rows`).

Changing either file changes `Expected.id`, so recipes approved for the old version stop
matching (design doc §5). The pack is not part of the id: it helps propose, it doesn't change
what the destination accepts.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

TYPES = ("string", "integer", "number", "date", "boolean")
OVERLAY_KEYS = {"type", "concept", "required", "enum", "pattern", "range", "unit", "case", "multiple", "on_missing",
                "description"}
DESTINATION_KEYS = {"$pack", "$group_by", "$repeat", "$fixed", "$targets", "$extension_base"}
DEFAULT_EXTENSION_BASE = "urn:multibridge:extension:"
MAX_FIELDS = 500
FIELDS_SUFFIX = ".fields.json"   # a saved field list: {"format": "csv", "fields": [{"name", "type", ...}]}
FIELD_KEYS = ("name", "type", "required", "multiple")
# Target attributes added after the first destinations: left out of the fingerprint while unset,
# so recipes approved before them keep matching.
NEWER = {"segments": None, "render": None, "group": None}


@dataclass
class Target:
    path: str                        # "cliente.fecha_alta", "pedido.lineas[].producto"
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
    multiple: str | None = None      # several source values: "first" | "join" | "list"; None = it's an error
    on_missing: str = "null"         # no data: "null" | "omit"
    segments: tuple[str, ...] | None = None   # nesting when the path can't be split on dots (a CSV header "F. Nac")
    render: dict | None = None       # how the writer shows the value, as in the example: {"date": "%d/%m/%Y", "decimal": ","}
    group: str | None = None         # the repeated group it belongs to: "pedido.lineas[]"

    @property
    def parts(self) -> tuple[str, ...]:
        return self.segments or tuple(self.path.split("."))

    @property
    def leaf(self) -> str:
        return self.parts[-1]


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


DATE_RENDER = {"dd/mm/yyyy": "%d/%m/%Y", "dd-mm-yyyy": "%d-%m-%Y", "dd.mm.yyyy": "%d.%m.%Y", "yyyymmdd": "%Y%m%d"}


def target_from_column(path: str, f, segments: tuple[str, ...] | None = None) -> Target:
    """A target from a profiled example column (CSV, Excel, XML text): its type and how it is written."""
    render: dict = {}
    if f.dtype in ("date", "datetime"):
        typ = "date"
        fmt = f.formats[0] if f.format == "mixed" and f.formats else f.format
        if fmt in DATE_RENDER:
            render["date"] = DATE_RENDER[fmt]
    elif f.dtype == "integer":
        typ = "integer"
    elif f.dtype == "decimal":
        typ = "number"
        if f.format == "decimal comma":
            render["decimal"] = ","
        places = {len(x.replace(",", ".").split(".", 1)[1]) for x in f.samples if "." in x.replace(",", ".")}
        if len(places) == 1:
            render["decimals"] = places.pop()     # "2.50": prices keep two decimals
    else:
        typ = "string"
    example = f.samples[0] if f.samples else None
    return Target(path=path, type=typ, example=example, description=f.description, unit=f.unit,
                  segments=segments, render=render or None, case=case_of(f.samples) if typ == "string" else None)


def case_of(samples: list[str]) -> str | None:
    """"title" when the example writes words like "Ana Ruiz": the output should look the same."""
    words_ = [w for s in samples for w in re.split(r"[\s-]+", str(s)) if w]
    small = ("de", "del", "la", "las", "los", "y")
    if (words_ and all(w.isalpha() for w in words_) and any(len(w) > 1 for w in words_)
            and all((w[0].isupper() and w[1:].islower()) or w.lower() in small for w in words_)):
        return "title"
    return None


def targets_from_example(example, pack=None) -> list[Target]:
    """Targets of a JSON example. Objects nest; a list of objects is a repeated group
    ("lineas[]"); a list of plain values is one target that takes several values."""
    from . import packs
    from .concepts import concept_for_name

    pack = pack or packs.NONE
    out: list[Target] = []

    def walk(obj: dict, prefix: str = "", group: str | None = None) -> None:
        for k, v in obj.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".", group)
            elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                if group:
                    raise ValueError(f"{path}: solo se admite un nivel de listas repetidas (dentro de {group})")
                walk(v[0], path + "[].", path + "[]")
            elif isinstance(v, list):
                first = next((x for x in v if x is not None), None)
                out.append(Target(path=path, type=_type_of(first), example=v, multiple="list",
                                  concept=concept_for_name(path, pack), group=group))
            else:
                out.append(Target(path=path, type=_type_of(v), example=v, concept=concept_for_name(path, pack),
                                  group=group))

    walk(example[0] if isinstance(example, list) else example)
    return out


def fields_from_rows(rows) -> list[dict]:
    """Every non-empty source column as a destination field, typed from its profile ("receive all
    the fields"). Typed only where it can't go wrong, the rest stays text, as it came:
      - dates become dates (ISO in the output); a datetime stays text (a date would lose the time)
      - decimals become numbers, and whole numbers only when the column has a unit ("Peso (kg)"):
        a postcode, a bed, a version "2.3" or a sequence number are digits, not quantities
      - identifiers, personal data and values a format declares as codes stay text
      - yes/no stays text (s/n, sí/no... aren't all booleans to the engine)
    The person can retype any field before using the list."""
    from .formats import declared_kind

    out = []
    for c, f in rows.columns.items():
        if f.dtype == "empty" or c.startswith("_"):
            continue
        plain = f.kind != "identifier" and not f.sensitive and declared_kind(f.declared_type) != "coded"
        typ = ("date" if f.dtype == "date" else
               "integer" if f.dtype == "integer" and plain and f.unit else
               "number" if f.dtype == "decimal" and plain else "string")
        many = any(isinstance(v, list) for v in rows.values(c))
        out.append({"name": c, "type": typ, "required": False, "multiple": "list" if many else None, "from": c,
                    "label": f.label, "description": f.description})
    return out


def save_fields(path: str | Path, fmt: str, fields: list[dict]) -> Path:
    """Write a field list as `<name>.fields.json`: structure only (names and types), never values."""
    p = Path(path)
    spec = {"format": fmt, "fields": [{k: f.get(k) for k in FIELD_KEYS if f.get(k) not in (None, False)}
                                      for f in fields]}
    p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def default_destination(folder: str | Path = "expected") -> Path:
    """The destination to use when none is named: the only `*.example.*` in the folder."""
    found = sorted(Path(folder).glob("*.example.*"))
    if len(found) != 1:
        names = ", ".join(p.name for p in found) or "ninguno"
        raise ValueError(f"indica el destino (--expected): en {folder} hay {len(found)} ejemplos ({names})")
    return found[0]


def destination_name(filename: str) -> str:
    stem = Path(filename).name
    if stem.endswith(FIELDS_SUFFIX):
        return stem[: -len(FIELDS_SUFFIX)]
    stem = stem[: -len(Path(stem).suffix)] if Path(stem).suffix else stem
    return stem.removesuffix(".example")


@dataclass
class Expected:
    name: str
    targets: list[Target]
    fingerprint: str
    pack: str | None = None          # domain pack name (packs/), from the overlay's "$pack"
    format: str = "json"             # the destination's format plug-in
    template: object = field(default=None, repr=False, compare=False)   # the example, for the writer
    group_by: str | None = None
    constants: dict = field(default_factory=dict)   # fixed values the template writes as they are
    extension_base: str = DEFAULT_EXTENSION_BASE

    @property
    def id(self) -> str:
        return f"{self.name}#{self.fingerprint}"

    def get(self, path: str) -> Target:
        for t in self.targets:
            if t.path == path:
                return t
        raise KeyError(path)

    @property
    def groups(self) -> list[str]:
        return list(dict.fromkeys(t.group for t in self.targets if t.group))

    @classmethod
    def from_example(cls, example, name: str, rules: dict | None = None) -> "Expected":
        """A JSON example (the original destination kind)."""
        from .formats import Destination

        return cls.build(Destination("json", targets_from_example(example), template=example), name, rules,
                         retarget=lambda pack: targets_from_example(example, pack))

    @classmethod
    def from_bytes(cls, data: bytes, filename: str, rules: dict | None = None, name: str | None = None) -> "Expected":
        """An example in any format, read by its format plug-in."""
        from . import formats, packs

        rules = dict(rules or {})
        options = {k: v for k, v in rules.items() if k.startswith("$")}
        pack = packs.get(options.get("$pack"))
        dest = formats.destination(data, filename, pack, options)
        return cls.build(dest, name or destination_name(filename), rules)

    @classmethod
    def from_fields(cls, fmt: str, fields: list[dict], name: str, options: dict | None = None) -> "Expected":
        """A destination with no example: a format plus a list of fields [{"name", "type", "required"?,
        "multiple"?}], typed by hand or taken from a source (fields_from_rows). The format plug-in
        gives it its plain shape (formats.Format.blank)."""
        from . import formats

        if not isinstance(fields, list) or not fields:
            raise ValueError("hace falta al menos un campo")
        if len(fields) > MAX_FIELDS:
            raise ValueError(f"demasiados campos (máximo {MAX_FIELDS})")
        clean, names = [], set()
        for n, f in enumerate(fields, start=1):
            if not isinstance(f, dict):
                raise ValueError(f"campo {n}: se espera un objeto")
            fname = str(f.get("name") or "").strip()
            if not fname or len(fname) > 200:
                raise ValueError(f"campo {n}: hace falta un nombre (hasta 200 caracteres)")
            if fname in names:
                raise ValueError(f"campo repetido: {fname}")
            names.add(fname)
            typ = f.get("type") or "string"
            if typ not in TYPES:
                raise ValueError(f"{fname}: tipo desconocido {typ!r}")
            multiple = f.get("multiple")
            if multiple not in (None, "list", "join", "first"):
                raise ValueError(f"{fname}: «multiple» no válido")
            clean.append({"name": fname, "type": typ, "required": bool(f.get("required")), "multiple": multiple})
        dest = formats.get(fmt).blank(clean, dict(options or {}))
        return cls.build(dest, name)

    @classmethod
    def build(cls, dest, name: str, rules: dict | None = None, retarget=None) -> "Expected":
        from . import packs
        from .concepts import concept_for_name, concept_for_text

        rules = dict(rules or {})
        unknown = {k for k in rules if k.startswith("$")} - DESTINATION_KEYS
        if unknown:
            raise ValueError(f"claves desconocidas en las reglas: {', '.join(sorted(unknown))}")
        pack_name = rules.pop("$pack", None)
        pack = packs.get(pack_name)
        group_by = rules.pop("$group_by", None)
        extension_base = rules.pop("$extension_base", DEFAULT_EXTENSION_BASE)
        for k in ("$repeat", "$fixed", "$targets"):
            rules.pop(k, None)   # used by the plug-in while reading the example
        targets = retarget(pack) if retarget else dest.targets
        for t in targets:
            if t.concept is None:
                t.concept = concept_for_name(t.path, pack) if not t.segments else concept_for_text(t.leaf, pack)
        known = {t.path: t for t in targets}
        for path, extra in rules.items():
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
            if t.concept is None and t.description:   # "Valor medido — peso corporal": the description says what it is
                t.concept = concept_for_text(t.description, pack)
        if group_by is not None and group_by not in known:
            raise ValueError(f"$group_by: '{group_by}' no es un campo del ejemplo")
        if group_by is not None and known[group_by].group:
            raise ValueError("$group_by: el campo clave no puede estar dentro de un grupo repetido")

        def spec_of(t: Target) -> dict:
            return {k: v for k, v in asdict(t).items() if k != "example" and not (k in NEWER and v == NEWER[k])}

        spec: object = [spec_of(t) for t in targets]
        if dest.format != "json" or group_by or dest.constants:
            spec = {"format": dest.format, "targets": spec, "group_by": group_by, "constants": dest.constants}
        text = json.dumps(spec, sort_keys=True, ensure_ascii=False, default=list)
        return cls(name=name, targets=targets, fingerprint=hashlib.sha256(text.encode()).hexdigest()[:8],
                   pack=pack_name, format=dest.format, template=dest.template, group_by=group_by,
                   constants=dest.constants, extension_base=extension_base)

    @classmethod
    def load(cls, example_path: str | Path, rules_path: str | Path | None = None) -> "Expected":
        """Load an example output; picks up `<name>.rules.json` next to `<name>.example.<ext>` automatically.
        A `<name>.fields.json` is a saved field list (no example)."""
        p = Path(example_path)
        name = destination_name(p.name)
        if p.name.endswith(FIELDS_SUFFIX):
            spec = json.loads(p.read_text(encoding="utf-8"))
            return cls.from_fields(spec.get("format"), spec.get("fields"), name)
        if rules_path is None:
            sibling = p.with_name(f"{name}.rules.json")
            rules_path = sibling if sibling.exists() else None
        rules = json.loads(Path(rules_path).read_text(encoding="utf-8")) if rules_path else None
        return cls.from_bytes(p.read_bytes(), p.name, rules=rules, name=name)

    # -- validation of one output value -----------------------------------------------------------
    @staticmethod
    def check(t: Target, value) -> str | None:
        """Why `value` breaks the target, or None. Never echoes the value: it may be personal data."""
        if isinstance(value, list) and t.multiple == "list":
            if not value:
                return "obligatorio sin valor" if t.required else None
            return next((p for p in (Expected.check(_single(t), v) for v in value) if p), None)
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


def _single(t: Target) -> Target:
    from dataclasses import replace
    return replace(t, multiple=None, required=True)
