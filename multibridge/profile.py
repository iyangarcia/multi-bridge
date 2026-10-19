"""Profile every Field and build the privacy-safe view the AI is allowed to see.

profile_dataset(ds)  fills dtype/format/unit/kind/sensitive/categories/concepts.
as_ai(ds, level)     returns what may leave the hospital: structure, types and
                     non-identifying categories. Never values of sensitive columns.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter

from .model import Dataset, Field
from .terms import get_normalizer
from .terms.base import AMBIGUOUS, MATCHED, UNKNOWN
from .terms.lexical import norm

# --- value types ------------------------------------------------------------------------------

DATE_FORMATS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d", "yyyy-mm-dd", "date"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"), None, "ISO 8601", "datetime"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "%d/%m/%Y", "dd/mm/yyyy", "date"),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"), "%d-%m-%Y", "dd-mm-yyyy", "date"),
    (re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$"), "%d.%m.%Y", "dd.mm.yyyy", "date"),
]
HL7_TS = [(8, "%Y%m%d", "yyyymmdd", "date"), (12, "%Y%m%d%H%M", "yyyymmddHHMM", "datetime"),
          (14, "%Y%m%d%H%M%S", "yyyymmddHHMMSS", "datetime")]
INT = re.compile(r"^[+-]?\d+$")
DEC_DOT = re.compile(r"^[+-]?\d+\.\d+$")
DEC_COMMA = re.compile(r"^[+-]?\d+,\d+$")
BOOL = {"true", "false", "si", "sí", "no", "s", "n", "yes", "y"}
ICD10 = re.compile(r"^[A-Z]\d{2}(\.[0-9A-Z]{1,4})?$")
TABLE_CODED = {"ID", "IS", "PT", "HD", "SI"}  # HL7 types whose values come from fixed code tables

UNITS = {"kg", "g", "mg", "cm", "m", "mm", "mmhg", "mg/dl", "mmol/l", "%", "°c", "ºc", "lpm", "rpm",
         "años", "anos", "meses", "dias", "días", "ml", "l", "ui", "kg/m2"}
UNIT_IN_LABEL = re.compile(r"[\(\[]\s*([^\)\]]{1,8})\s*[\)\]]\s*$|[_\s]([a-zA-Z%/0-9]{1,6})$")


def _valid(v: str, fmt: str) -> bool:
    try:
        dt.datetime.strptime(v, fmt)
        return True
    except ValueError:
        return False


def value_type(v: str, declared: str | None) -> tuple[str, str | None]:
    if declared in ("TS", "DT", "DTM"):
        digits = v.split("+")[0].split("-")[0].split(".")[0]
        for n, fmt, label, kind in HL7_TS:
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
    # HL7 table-coded fields (event "A01", coding system "I10") look like ICD-10 but are not
    if ICD10.match(v) and declared not in TABLE_CODED:
        return "code", "ICD-10"
    return "string", None


# --- sensitivity ------------------------------------------------------------------------------

NAME_HINTS = {
    "documento de identidad": ["dni", "nif", "nie", "pasaporte", "ssn", "seguridad social", "nss", "pid 19"],
    "identificador del paciente": ["nhc", "historia", "mrn", "identifier", "identificador", "cip",
                                   "tarjeta sanitaria", "pid 3", "pid 2", "pid 18"],
    "nombre": ["nombre", "apellido", "apellidos", "name", "given", "family", "pid 5", "pid 6", "nk1 2"],
    "contacto": ["telefono", "movil", "phone", "telecom", "email", "correo", "pid 13", "pid 14"],
    "dirección": ["domicilio", "direccion", "calle", "address line", "street", "pid 11 1", "pid 11 2"],
    "fecha de nacimiento": ["nacimiento", "birth", "birthdate", "dob", "f nac", "pid 7"],
    "nombre de profesional": ["medico", "doctor", "practitioner", "facultativo", "pv1 7"],
}
VALUE_PATTERNS = {
    "DNI": re.compile(r"^\d{8}[A-Za-z]$"),
    "NIE": re.compile(r"^[XYZxyz]\d{7}[A-Za-z]$"),
    "teléfono": re.compile(r"^(\+?34)?[6789]\d{8}$"),
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I),
}
ID_REASONS = {"documento de identidad", "identificador del paciente"}


def _words(f: Field) -> str:
    camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", f"{f.path} {f.label}")
    return f" {norm(camel)} "


def _sensitivity(f: Field, values: list[str]) -> str | None:
    words = _words(f)
    # Metadata next to a sensitive value is not itself personal data:
    # FHIR "identifier.system", "telecom.use"; HL7 PID-3.4..6 (who issued the ID, ID type)
    is_metadata = re.search(r"\.(system|use|type)$|^PID-3\.[4-6]$", f.path) is not None
    for reason, hints in NAME_HINTS.items():
        if not is_metadata and any(f" {h} " in words for h in hints):
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


def profile_field(f: Field, values: list, normalizer=None) -> None:
    flat, nulls = _flat(values)
    f.null_ratio = round(nulls / len(values), 2) if values else 1.0
    f.distinct = len(set(flat))
    f.samples = list(dict.fromkeys(flat))[:5]

    if not flat:
        f.dtype, f.kind = "empty", "value"
        return
    if f.path.startswith("_"):  # synthetic link added by a parser (HL7 _message)
        f.dtype, f.kind = "string", "reference"
        return

    types = Counter(value_type(v, f.declared_type) for v in flat)
    (dtype, fmt), n = types.most_common(1)[0]
    kinds = Counter(t for t, _ in types.elements())
    if {"integer", "decimal"} >= set(kinds) and len(kinds) == 2:
        dtype, fmt = "decimal", next((fm for (t, fm) in types if t == "decimal" and fm), None)
    elif n < 0.9 * len(flat):
        dtype, fmt = "string", None
    f.dtype, f.format = dtype, fmt

    m = UNIT_IN_LABEL.search(f.label or f.path)
    if m:
        unit = (m.group(1) or m.group(2) or "").strip().lower()
        if unit in UNITS:
            f.unit = unit

    reason = _sensitivity(f, flat)
    f.sensitive, f.sensitive_reason = reason is not None, reason

    avg_len = sum(len(v) for v in flat) / len(flat)
    id_shaped = sum(bool(re.search(r"[A-Za-z]", v) and re.search(r"\d", v) and " " not in v) for v in flat)
    if reason in ID_REASONS or (f.distinct == len(flat) and len(flat) > 3 and dtype == "string"
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

    if (dtype in ("string", "code") and not f.sensitive and normalizer is not None and f.kind != "identifier"
            and f.declared_type not in TABLE_CODED):
        _concepts(f, flat, normalizer)


def _concepts(f: Field, flat: list[str], normalizer) -> None:
    distinct = list(dict.fromkeys(flat))[:200]
    results = {v: normalizer.normalize(v) for v in distinct}
    recognised = sum(1 for ms in results.values() if ms and all(m.status != UNKNOWN for m in ms))
    if recognised < max(1, 0.4 * len(distinct)):
        return
    f.kind = "clinical_concept"
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


def profile_dataset(ds: Dataset, normalizer=None) -> Dataset:
    normalizer = normalizer or get_normalizer()
    for f in ds.fields:
        profile_field(f, ds.values(f), normalizer)
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
