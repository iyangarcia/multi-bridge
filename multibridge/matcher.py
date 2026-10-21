"""Rules proposer: the offline fallback that drafts a recipe when no local model is available.

For every target field it scores every source column on concept evidence (standard
HL7/FHIR position, name, description, values), role (patient vs doctor), type and unit;
assigns greedily one-to-one; and works out the transforms. The local Qwen proposer
(docs/ROADMAP.md, phase 2) produces the same recipe shape.

Scores are hand-weighted rules, NOT probabilities (recipe.CONFIDENCE_KIND).
"""

from __future__ import annotations

import re

from . import recipe
from .concepts import CONCEPTS, NAME_PARTS, Evidence, _flat, evidence, translate, words
from .expected import Expected, Target
from .model import Field
from .records import Rows

THRESHOLD = 0.6
DATE_FORMATS = {"dd/mm/yyyy": "%d/%m/%Y", "dd-mm-yyyy": "%d-%m-%Y", "dd.mm.yyyy": "%d.%m.%Y",
                "yyyymmdd": "%Y%m%d", "yyyymmddHHMM": "%Y%m%d", "yyyymmddHHMMSS": "%Y%m%d", "ISO 8601": "iso"}
UNIT_FACTORS = {("g", "kg"): 0.001, ("lb", "kg"): 0.45359237, ("m", "cm"): 100, ("mm", "cm"): 0.1}
TYPE_OK = {"date": {"date", "datetime"}, "number": {"integer", "decimal"}, "integer": {"integer"},
           "boolean": {"boolean"}}
OBSERVATION_VALUES = {"OBX-5", "valueQuantity.value", "valueString", "valueCodeableConcept.text"}


def _bigrams(s: str) -> list[str]:
    s = s.replace(" ", "")
    return [s[i:i + 2] for i in range(len(s) - 1)]


def dice(a: str, b: str) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    rest, common = list(B), 0
    for x in A:
        if x in rest:
            rest.remove(x)
            common += 1
    return 2 * common / (len(A) + len(B))


def score(f: Field, ev: Evidence, t: Target) -> tuple[float, list[str]]:
    why: list[str] = []
    w = ev.weights.get(t.concept, 0) if t.concept else 0
    if w:
        s = 0.55 + 0.35 * w + (0.04 if ev.kinds[t.concept] == "standard" else 0)
        why.append(ev.reasons[t.concept])
    else:
        sim = dice(words(f.label).strip(), words(t.leaf).strip())
        s = 0.45 * sim
        if sim > 0.5:
            why.append("nombre parecido")
    others = [v for k, v in ev.weights.items() if k != t.concept and not (t.concept == "medico" and k in NAME_PARTS)]
    if others:
        s -= 0.1 * max(others)
    if ev.role != (CONCEPTS[t.concept].role if t.concept in CONCEPTS else "patient"):
        s -= 0.35
        why.append(f"pertenece a otra persona ({ev.role})")
    if f.kind == "clinical_concept" and t.concept != "diagnostico":
        s -= 0.3   # the messy Excel's "Diagnóstico principal" (documented as "texto libre del médico") is not a doctor
        why.append("la columna contiene diagnósticos")
    if f.dtype == "empty":
        s -= 0.5
    elif t.type in TYPE_OK and f.dtype not in TYPE_OK[t.type]:
        s -= 0.3
        why.append(f"tipo incompatible ({f.dtype} → {t.type})")
    if t.unit and f.unit and f.unit != t.unit and (f.unit, t.unit) not in UNIT_FACTORS:
        s -= 0.3
        why.append(f"unidad distinta ({f.unit} → {t.unit})")
    return max(0.0, min(0.99, round(s, 3))), why


def transforms_for(rows: Rows, cols: list[str], t: Target) -> tuple[list[dict], list[str], bool]:
    """(transforms, issues, needs_human) to turn these source columns into the target's type and format."""
    out: list[dict] = []
    issues: list[str] = []
    pending = False
    f = rows.columns[cols[0]]
    values = [v for c in cols for v in rows.values(c)]
    flat = _flat(values)

    if len(cols) > 1:
        out.append({"op": "join_columns", "sep": " "})
    if t.type == "date" and f.format in DATE_FORMATS:
        out.append({"op": "date", "from": DATE_FORMATS[f.format]})
    if t.type in ("number", "integer"):
        out.append({"op": "number", "decimal": ","} if f.format == "decimal comma" else {"op": "number"})
        if t.unit and f.unit and (f.unit, t.unit) in UNIT_FACTORS:
            out.append({"op": "scale", "factor": UNIT_FACTORS[(f.unit, t.unit)]})
            issues.append(f"se convierte {f.unit} → {t.unit}")
    if t.enum is not None:
        tr = translate(t.concept, flat)
        changes = {k: v for k, v in sorted(tr.items()) if v is not None and v != k}
        untranslated = sorted(k for k, v in tr.items() if v is None and k not in t.enum)
        if changes:
            out.append({"op": "translate", "values": changes})
        if untranslated:
            pending = True
            issues.append(f"valores sin traducción al catálogo: {', '.join(untranslated)}")
    if t.case == "title":
        alpha = [v for v in flat if any(c.isalpha() for c in v)]
        if alpha and sum(v.isupper() for v in alpha) >= 0.8 * len(alpha):
            out.append({"op": "title"})
    if t.pattern and t.pattern.startswith("\\+") and any(not v.startswith(("+", "00")) for v in flat):
        out.append({"op": "phone", "country": "34"})
        issues.append("números sin prefijo: se asume +34 (España)")
    m = re.fullmatch(r"\[0-9\]\{(\d+)\}", t.pattern or "")
    if m and f.dtype == "integer":
        out.append({"op": "pad", "width": int(m.group(1))})

    # OBX-5 / Observation.value hold weight in one row and height in another; the code says which.
    if f.path in OBSERVATION_VALUES or (f.entity in ("OBX", "Observation") and "value" in f.path.lower()):
        pending = True
        issues.append("valor de observación: depende del código (OBX-3 / Observation.code); "
                      "hace falta filtrar por código, aún no soportado")

    if any(isinstance(v, list) for v in values):
        if t.multiple == "join":
            out.append({"op": "join_values", "sep": "; "})
        else:
            out.append({"op": "first"})
            issues.append("hay varios valores en origen: se toma el primero")
    return out, issues, pending


def _composite_name(rows: Rows, evs: dict[str, Evidence], t: Target) -> tuple[str, str] | None:
    """A doctor's full name split into given/family components (HL7 PV1-7.3 + PV1-7.2)."""
    if t.concept != "medico":
        return None
    people = [c for c, f in rows.columns.items() if evs[c].role == "practitioner" and "." in f.path]
    for given in (c for c in people if evs[c].weights.get("nombre", 0) >= 0.9):
        parent = rows.columns[given].path.rsplit(".", 1)[0]
        family = next((c for c in people if rows.columns[c].entity == rows.columns[given].entity
                       and rows.columns[c].path.rsplit(".", 1)[0] == parent
                       and evs[c].weights.get("apellidos", 0) >= 0.9), None)
        if family:
            return given, family
    return None


def propose(rows: Rows, expected: Expected, name: str | None = None) -> dict:
    usable = [c for c, f in rows.columns.items() if f.dtype != "empty"]
    evs = {c: evidence(f, rows.values(c)) for c, f in rows.columns.items()}

    pairs: list[tuple[float, str, tuple[str, ...], list[str]]] = []
    for t in expected.targets:
        for c in usable:
            s, why = score(rows.columns[c], evs[c], t)
            pairs.append((s, t.path, (c,), why))
        combo = _composite_name(rows, evs, t)
        if combo:
            pairs.append((0.82, t.path, combo, ["nombre y apellidos del médico en columnas separadas: se unen"]))
    pairs.sort(key=lambda p: -p[0])

    chosen: dict[str, tuple[float, tuple[str, ...], list[str]]] = {}
    used: set[str] = set()
    for s, target, cols, why in pairs:
        if s < THRESHOLD:
            break
        if target not in chosen and not used & set(cols):
            chosen[target] = (s, cols, why)
            used |= set(cols)

    fields: dict[str, dict] = {}
    for t in expected.targets:
        if t.path in chosen:
            s, cols, why = chosen[t.path]
            transforms, issues, pending = transforms_for(rows, list(cols), t)
            for c in cols:
                if evs[c].kinds.get(t.concept) == "values":
                    issues.append("deducido solo por los valores: revisar")
                if rows.columns[c].custom:
                    issues.append("campo personalizado del centro (no estándar)")
            fields[t.path] = {"status": "pending" if pending else "mapped", "from": list(cols),
                              "transforms": transforms, "confidence": s, "why": why,
                              "issues": list(dict.fromkeys(issues))}
        else:
            best = sorted((p for p in pairs if p[1] == t.path and p[0] > 0.2), key=lambda p: -p[0])[:3]
            fields[t.path] = {"status": "pending" if t.required else "no_data", "from": [], "transforms": [],
                              "confidence": None, "why": ["ninguna columna de origen supera el umbral"],
                              "issues": ["obligatorio: hay que asignar un origen o un valor por defecto"]
                              if t.required else [],
                              "candidates": [{"column": p[2][0], "confidence": p[0]} for p in best]}
    return recipe.new(name or rows.source.rsplit(".", 1)[0], rows, expected, fields, proposed_by="rules")
