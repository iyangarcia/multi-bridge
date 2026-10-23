"""Profile every Field and build the privacy-safe view the AI is allowed to see.

profile_dataset(ds)  fills dtype/format/unit/kind/sensitive/categories/concepts.
as_ai(ds, level)     returns what may leave the organisation: structure, types and
                     non-identifying categories. Never values of sensitive columns.

The core detects general personal data (names, ID documents, contact, addresses, dates of
birth). Every installed domain pack adds its own hints, code shapes and terminology
(packs/): before the destination is known, over-detecting is the safe side.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter

from .concepts import words as _text
from .model import Dataset, Field, is_metadata
from .terminology import AMBIGUOUS, MATCHED, UNKNOWN

# --- value types ------------------------------------------------------------------------------

DATE_FORMATS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d", "yyyy-mm-dd", "date"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"), None, "ISO 8601", "datetime"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "%d/%m/%Y", "dd/mm/yyyy", "date"),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"), "%d-%m-%Y", "dd-mm-yyyy", "date"),
    (re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$"), "%d.%m.%Y", "dd.mm.yyyy", "date"),
]
# Compact timestamps, read only where a format declares a timestamp type
COMPACT_TS = [(8, "%Y%m%d", "yyyymmdd", "date"), (12, "%Y%m%d%H%M", "yyyymmddHHMM", "datetime"),
              (14, "%Y%m%d%H%M%S", "yyyymmddHHMMSS", "datetime")]
INT = re.compile(r"^[+-]?\d+$")
DEC_DOT = re.compile(r"^[+-]?\d+\.\d+$")
DEC_COMMA = re.compile(r"^[+-]?\d+,\d+$")
BOOL = {"true", "false", "si", "sí", "no", "s", "n", "yes", "y"}

UNITS = {"kg", "g", "mg", "cm", "m", "mm", "mmhg", "mg/dl", "mmol/l", "%", "°c", "ºc", "lpm", "rpm",
         "años", "anos", "meses", "dias", "días", "ml", "l", "ui", "kg/m2"}
UNIT_IN_LABEL = re.compile(r"[\(\[]\s*([^\)\]]{1,8})\s*[\)\]]\s*$|[_\s]([a-zA-Z%/0-9]{1,6})$")


def _valid(v: str, fmt: str) -> bool:
    try:
        dt.datetime.strptime(v, fmt)
        return True
    except ValueError:
        return False


def _declared(declared: str | None) -> str | None:
    from .formats import declared_kind
    return declared_kind(declared)


def _packs(packs):
    from . import packs as registry
    return registry.installed() if packs is None else list(packs)


def value_type(v: str, declared: str | None, packs=None) -> tuple[str, str | None]:
    kind_declared = _declared(declared)
    if kind_declared == "timestamp":
        digits = v.split("+")[0].split("-")[0].split(".")[0]
        for n, fmt, label, kind in COMPACT_TS:
            if len(digits) == n and digits.isdigit() and _valid(digits, fmt):
                return kind, label
    for rx, fmt, label, kind in DATE_FORMATS:
        # The shape decides the format; an impossible date (31/02) is the engine's job to reject,
        # not a reason to stop treating the whole column as dates.
        if rx.match(v):
            return kind, label
    if INT.match(v):
        return ("string", "leading zeros") if len(v) > 1 and v.lstrip("+-").startswith("0") else ("integer", None)
    if DEC_DOT.match(v):
        return "decimal", None
    if DEC_COMMA.match(v):
        return "decimal", "decimal comma"
    if v.lower() in BOOL:
        return "boolean", None
    # Values a format declares as table-coded (event "A01", coding system "I10") look like codes but are not
    if kind_declared != "coded":
        for pack in _packs(packs):
            for label, rx in pack.code_patterns:
                if rx.match(v):
                    return "code", label
    return "string", None


# --- sensitivity ------------------------------------------------------------------------------

# (rank, reason, field-name hints). Packs add theirs; a lower rank is checked first.
NAME_HINTS = [
    (10, "documento de identidad", ["dni", "nif", "nie", "pasaporte", "ssn", "seguridad social", "nss"]),
    (21, "identificador", ["identifier", "identificador"]),
    (30, "nombre", ["nombre", "apellido", "apellidos", "name", "given", "family"]),
    (40, "contacto", ["telefono", "movil", "phone", "telecom", "email", "correo"]),
    (50, "dirección", ["domicilio", "direccion", "calle", "address line", "street"]),
    (60, "fecha de nacimiento", ["nacimiento", "birth", "birthdate", "dob", "f nac"]),
    # GDPR art. 9 special categories, in any domain
    (80, "categoría especial (art. 9 RGPD)", ["salud", "health", "religion", "creencias", "etnia", "ethnic",
                                               "raza", "race", "sindicato", "union membership",
                                               "orientacion sexual", "sexual orientation", "vida sexual",
                                               "opinion politica", "political", "afiliacion politica",
                                               "genetico", "genetic", "biometrico", "biometric"]),
]
VALUE_PATTERNS = {
    "DNI": re.compile(r"^\d{8}[A-Za-z]$"),
    "NIE": re.compile(r"^[XYZxyz]\d{7}[A-Za-z]$"),
    "teléfono": re.compile(r"^(\+?34)?[6789]\d{8}$"),
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I),
    "IBAN": re.compile(r"^[A-Z]{2}\d{2}( ?[A-Z0-9]{4}){3,7}( ?[A-Z0-9]{1,4})?$"),
    # "Ana Ruiz", "María de la Paz Gil": two to five capitalised words of letters only. Product names
    # match too; hiding them from the AI is the safe side of the mistake.
    "nombre de persona": re.compile(r"^[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(-[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)?"
                                    r"( (de |del |de la |de los )?[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+"
                                    r"(-[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)?){1,4}$"),
}
ID_REASONS = {"documento de identidad", "identificador"}


def _name_hints(packs) -> list[tuple[str, list[str]]]:
    merged: dict[str, tuple[int, list[str]]] = {}
    for rank, reason, hints in NAME_HINTS + [x for p in packs for x in p.sensitive]:
        old = merged.get(reason)
        merged[reason] = (min(rank, old[0]) if old else rank, (old[1] if old else []) + hints)
    return [(reason, hints) for reason, (_, hints) in sorted(merged.items(), key=lambda x: x[1][0])]


def _sensitivity(f: Field, values: list[str], packs) -> str | None:
    words = _text(f.path, f.label)
    # Metadata next to a sensitive value is not itself personal data ("identifier.system", "telecom.use",
    # or what a pack says: who issued an ID, its type)
    metadata = is_metadata(f.path) or any(p.not_personal(f) for p in packs)
    for reason, hints in _name_hints(packs):
        if not metadata and any(f" {h} " in words for h in hints):
            return reason
    for label, rx in VALUE_PATTERNS.items():
        if values and sum(bool(rx.match(v)) for v in values) >= 0.5 * len(values):
            return f"valores con formato de {label}"
    return None


# --- profiling --------------------------------------------------------------------------------

def _flat(values) -> tuple[list[str], int]:
    out, nulls = [], 0
    for v in values:
        if v is None or v == "" or v == []:
            nulls += 1
        elif isinstance(v, list):
            out += [x for x in v if x]
        else:
            out.append(v)
    return out, nulls


_NORMALIZERS: dict[str, object] = {}


def _normalizers(packs, normalizer=None) -> list[tuple[object, str]]:
    """(normalizer, Field.kind it gives) per pack that has one. Built once per pack."""
    out = []
    for p in packs:
        if normalizer is not None:
            return [(normalizer, p.concept_kind)]
        if p.name not in _NORMALIZERS:
            _NORMALIZERS[p.name] = p.normalizer()
        if _NORMALIZERS[p.name] is not None:
            out.append((_NORMALIZERS[p.name], p.concept_kind))
    return out


def profile_field(f: Field, values: list, normalizer=None, packs=None) -> None:
    """`packs`: the domain packs whose detectors run (default: every installed one)."""
    packs = _packs(packs)
    flat, nulls = _flat(values)
    f.null_ratio = round(nulls / len(values), 2) if values else 1.0
    f.distinct = len(set(flat))
    f.samples = list(dict.fromkeys(flat))[:5]

    if not flat:
        f.dtype, f.kind = "empty", "value"
        return
    if f.path.startswith("_"):  # synthetic link added by a parser (a message id)
        f.dtype, f.kind = "string", "reference"
        return

    types = Counter(value_type(v, f.declared_type, packs) for v in flat)
    (dtype, fmt), n = types.most_common(1)[0]
    kinds = Counter(t for t, _ in types.elements())
    formats = None
    if {"integer", "decimal"} >= set(kinds) and len(kinds) == 2:
        dtype, fmt = "decimal", next((fm for (t, fm) in types if t == "decimal" and fm), None)
    elif set(kinds) <= {"date", "datetime"} and len({fm for _, fm in types}) > 1:
        # One column, several date shapes: 19601105 next to 198504121030, or an Excel column with
        # real dates and typed "05/11/1960". Still dates; the engine tries each format in turn.
        dtype, fmt = kinds.most_common(1)[0][0], "mixed"
        formats = sorted({fm for _, fm in types})
    elif n < 0.9 * len(flat):
        dtype, fmt = "string", None
    f.dtype, f.format, f.formats = dtype, fmt, formats

    m = UNIT_IN_LABEL.search(f.label or f.path)
    if m:
        unit = (m.group(1) or m.group(2) or "").strip().lower()
        if unit in UNITS:
            f.unit = unit

    reason = _sensitivity(f, flat, packs)
    f.sensitive, f.sensitive_reason = reason is not None, reason

    avg_len = sum(len(v) for v in flat) / len(flat)
    id_shaped = sum(bool(re.search(r"[A-Za-z]", v) and re.search(r"\d", v) and " " not in v) for v in flat)
    id_reasons = ID_REASONS | {r for p in packs for r in p.id_reasons}
    if reason in id_reasons or (f.distinct == len(flat) and len(flat) > 3 and dtype == "string"
                                and id_shaped >= 0.8 * len(flat)):
        f.kind = "identifier"
    elif dtype == "code":
        f.kind = "coded"
    elif dtype == "string" and not f.sensitive and f.distinct <= 10 and (
            f.distinct <= 3 or avg_len <= 4 or len(flat) >= 2 * f.distinct):
        f.kind = "categorical"
        f.categories = sorted(set(flat))
    elif dtype == "string" and (avg_len >= 15 or sum(" " in v for v in flat) > len(flat) / 2):
        f.kind = "free_text"

    if dtype in ("string", "code") and not f.sensitive and f.kind != "identifier" \
            and _declared(f.declared_type) != "coded":
        for norm, kind in _normalizers(packs, normalizer):
            if _concepts(f, flat, norm, kind):
                break


def _concepts(f: Field, flat: list[str], normalizer, kind: str) -> bool:
    distinct = list(dict.fromkeys(flat))[:200]
    results = {v: normalizer.normalize(v) for v in distinct}
    recognised = sum(1 for ms in results.values() if ms and all(m.status != UNKNOWN for m in ms))
    if recognised < max(1, 0.4 * len(distinct)):
        return False
    f.kind = kind
    if f.categories:
        f.categories = None
    statuses = Counter(m.status for ms in results.values() for m in ms)
    f.concepts = {
        "normalizer": normalizer.name,
        "values": len(distinct),
        "recognised": recognised,
        "matched": statuses[MATCHED],
        "ambiguous": sorted({m.text for ms in results.values() for m in ms if m.status == AMBIGUOUS}),
        "unknown": sorted({m.text for ms in results.values() for m in ms if m.status == UNKNOWN}),
        "qualifiers": dict(Counter(m.qualifier for ms in results.values() for m in ms)),
        "systems": sorted({m.system for ms in results.values() for m in ms if m.system}),
    }
    return True


def profile_dataset(ds: Dataset, normalizer=None, packs=None) -> Dataset:
    packs = _packs(packs)
    for f in ds.fields:
        profile_field(f, ds.values(f), normalizer, packs)
    return ds


# --- what the AI may see ----------------------------------------------------------------------

LEVELS = ("structure", "profile")


def as_ai(ds: Dataset, level: str = "profile") -> dict:
    """Metadata only. Values never leave, except non-identifying categories (H/M, A+...)."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    entities = []
    for entity in ds.entities():
        fields = []
        for f in (x for x in ds.fields if x.entity == entity):
            item = {"path": f.path, "label": f.label, "description": f.description, "custom": f.custom}
            if level == "profile":
                item.update(dtype=f.dtype, format=f.format, unit=f.unit, kind=f.kind, null_ratio=f.null_ratio)
                if f.sensitive:
                    item["withheld"] = f"valores ocultos ({f.sensitive_reason})"
                elif f.categories:
                    item["categories"] = f.categories
                if f.concepts:
                    item["concepts"] = {k: v for k, v in f.concepts.items() if k not in ("ambiguous", "unknown")}
                    item["concepts"]["pending_review"] = len(f.concepts["ambiguous"]) + len(f.concepts["unknown"])
            fields.append(item)
        entities.append({"entity": entity, "rows": len(ds.tables[entity]), "fields": fields})
    return {"source_format": ds.format, "level": level, "entities": entities}
