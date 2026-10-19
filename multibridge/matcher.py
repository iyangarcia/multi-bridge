"""Rules matcher: propose a mapping plan (a draft driver) from any Dataset to a Contract.

For every target field it scores every source field on: concept evidence
(standard position, name, description, values), role (patient vs doctor),
type and unit compatibility. Then it assigns greedily one-to-one, works out
the transformations, and lists what's left unmatched on both sides.

The score is a rules similarity, NOT a calibrated probability (design doc §8).
It orders the review; it never replaces approval. The local model / Jev
deciders (docs/JEV.md) will plug in here for the cases rules can't settle.
"""

from __future__ import annotations

import datetime as dt
import re

from .concepts import CONCEPTS, NAME_PARTS, Evidence, _flat, evidence, translate, words
from .contract import Contract, TargetField
from .model import Dataset, Field

THRESHOLD = 0.6
SCORE_KIND = "similitud por reglas, sin calibrar (ordena la revisión; no es una probabilidad)"

DATE_FORMATS = {"dd/mm/yyyy": "%d/%m/%Y", "dd-mm-yyyy": "%d-%m-%Y", "dd.mm.yyyy": "%d.%m.%Y",
                "yyyymmdd": "%Y%m%d", "yyyymmddHHMM": "%Y%m%d", "yyyymmddHHMMSS": "%Y%m%d", "ISO 8601": "iso"}
UNIT_FACTORS = {("g", "kg"): 0.001, ("lb", "kg"): 0.45359237, ("m", "cm"): 100, ("mm", "cm"): 0.1}
OBSERVATION_VALUES = {"OBX-5", "valueQuantity.value", "valueString", "valueCodeableConcept.text"}
TYPE_OK = {"date": {"date", "datetime"}, "number": {"integer", "decimal"}, "integer": {"integer"},
           "boolean": {"boolean"}}


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


def score(f: Field, ev: Evidence, t: TargetField) -> tuple[float, list[str]]:
    reasons: list[str] = []
    w = ev.weights.get(t.concept, 0) if t.concept else 0
    if w:
        s = 0.55 + 0.35 * w + (0.04 if ev.kinds[t.concept] == "standard" else 0)
        reasons.append(ev.reasons[t.concept])
    else:
        sim = dice(words(f.label).strip(), words(t.leaf).strip())
        s = 0.45 * sim
        if sim > 0.5:
            reasons.append("nombre parecido")
    others = [v for k, v in ev.weights.items()
              if k != t.concept and not (t.concept == "medico" and k in NAME_PARTS)]
    if others:
        s -= 0.1 * max(others)
    target_role = CONCEPTS[t.concept].role if t.concept in CONCEPTS else "patient"
    if ev.role != target_role:
        s -= 0.35
        reasons.append(f"pertenece a otra persona ({ev.role})")
    if f.dtype == "empty":
        s -= 0.5
    elif t.type in TYPE_OK and f.dtype not in TYPE_OK[t.type]:
        s -= 0.3
        reasons.append(f"tipo incompatible ({f.dtype} → {t.type})")
    if t.unit and f.unit and f.unit != t.unit and (f.unit, t.unit) not in UNIT_FACTORS:
        s -= 0.3
        reasons.append(f"unidad distinta ({f.unit} → {t.unit})")
    return max(0.0, min(0.99, round(s, 3))), reasons


def _ops(ds: Dataset, sources: list[Field], t: TargetField, root: str) -> tuple[list[dict], list[str], bool]:
    """Transformations from source values to the target's type/format. Returns (ops, issues, needs_human)."""
    ops: list[dict] = []
    issues: list[str] = []
    pending = False
    f = sources[0]
    values = [v for s in sources for v in ds.values(s)]
    flat = _flat(values)

    if len(sources) > 1:
        ops.append({"op": "concat", "sep": " "})
    if t.type == "date" and f.format in DATE_FORMATS:
        ops.append({"op": "date", "from": DATE_FORMATS[f.format]})
    if t.type in ("number", "integer"):
        ops.append({"op": "number", "decimal": ","} if f.format == "decimal comma" else {"op": "number"})
        if t.unit and f.unit and (f.unit, t.unit) in UNIT_FACTORS:
            ops.append({"op": "scale", "factor": UNIT_FACTORS[(f.unit, t.unit)]})
            issues.append(f"se convierte {f.unit} → {t.unit}")
    if t.enum is not None:
        tr = translate(t.concept, flat)
        changes = {k: v for k, v in sorted(tr.items()) if v is not None and v != k}
        untranslated = sorted(k for k, v in tr.items() if v is None and k not in t.enum)
        if changes:
            ops.append({"op": "map", "values": changes})
        if untranslated:
            pending = True
            issues.append(f"valores sin traducción al catálogo: {', '.join(untranslated)}")
    if t.case == "title":
        alpha = [v for v in flat if any(c.isalpha() for c in v)]
        if alpha and sum(v.isupper() for v in alpha) >= 0.8 * len(alpha):
            ops.append({"op": "title"})
    if t.pattern and t.pattern.startswith("\\+") and any(not v.startswith(("+", "00")) for v in flat):
        ops.append({"op": "phone", "country": "34"})
        issues.append("números sin prefijo: se asume +34 (España)")
    m = re.fullmatch(r"\[0-9\]\{(\d+)\}", t.pattern or "")
    if m and f.dtype == "integer":
        ops.append({"op": "pad", "width": int(m.group(1))})

    # Key-value rows: OBX-5 / Observation.value hold weight in one row and height in the next;
    # which is which depends on the code (OBX-3 / Observation.code). Needs a filter: not supported yet.
    if f.path in OBSERVATION_VALUES or f.entity in ("OBX", "Observation") and "value" in f.path.lower():
        pending = True
        issues.append("valor de observación: depende del código (OBX-3 / Observation.code); "
                      "hace falta filtrar por código, aún no soportado")

    repeated = any(isinstance(v, list) and len(v) > 1 for v in values) or f.entity != root
    if repeated:
        if t.multiple == "join":
            ops.append({"op": "join", "sep": "; "})
        else:
            ops.append({"op": "first"})
            if any(isinstance(v, list) and len(v) > 1 for v in values):
                issues.append("hay varios valores en origen: se toma el primero")
    return ops, issues, pending


def _composite_name(ds: Dataset, evs: dict[str, Evidence], t: TargetField) -> tuple[Field, Field] | None:
    """A doctor's full name split in given/family components (HL7 PV1-7.3 + PV1-7.2)."""
    if t.concept != "medico":
        return None
    people = [f for f in ds.fields if evs[f.key].role == "practitioner" and "." in f.path]
    for given in (f for f in people if evs[f.key].weights.get("nombre", 0) >= 0.9):
        parent = given.path.rsplit(".", 1)[0]
        family = next((f for f in people if f.entity == given.entity and f.path.rsplit(".", 1)[0] == parent
                       and evs[f.key].weights.get("apellidos", 0) >= 0.9), None)
        if family:
            return given, family
    return None


def _src(f: Field) -> dict:
    return {"entity": f.entity, "path": f.path, "label": f.label}


def propose(ds: Dataset, contract: Contract, name: str | None = None) -> dict:
    usable = [f for f in ds.fields if f.dtype != "empty" and not f.path.startswith("_")]
    evs = {f.key: evidence(f, ds.values(f)) for f in ds.fields}

    pairs: list[tuple[float, str, tuple[Field, ...], list[str]]] = []
    for t in contract.fields:
        for f in usable:
            s, reasons = score(f, evs[f.key], t)
            pairs.append((s, t.path, (f,), reasons))
        combo = _composite_name(ds, evs, t)
        if combo:
            pairs.append((0.82, t.path, combo, ["nombre y apellidos del médico en campos separados: se unen"]))
    pairs.sort(key=lambda p: -p[0])

    chosen: dict[str, tuple[float, tuple[Field, ...], list[str]]] = {}
    used: set[str] = set()
    for s, target, sources, reasons in pairs:
        if s < THRESHOLD:
            break
        if target in chosen or any(f.key in used for f in sources):
            continue
        chosen[target] = (s, sources, reasons)
        used |= {f.key for f in sources}

    counts: dict[str, int] = {}
    for _, sources, _ in chosen.values():
        for f in sources:
            counts[f.entity] = counts.get(f.entity, 0) + 1
    root = max(counts, key=counts.get) if counts else (ds.entities()[0] if ds.entities() else None)
    join = None
    if len(counts) > 1:
        join = "hl7_message" if ds.format == "hl7v2" else "fhir_reference" if ds.format == "fhir" else None

    mappings = []
    for t in contract.fields:
        if t.path in chosen:
            s, sources, reasons = chosen[t.path]
            ops, issues, pending = _ops(ds, list(sources), t, root)
            for f in sources:
                kind = evs[f.key].kinds.get(t.concept)
                if kind == "values":
                    issues.append("deducido solo por los valores: revisar")
                if f.custom:
                    issues.append("campo personalizado del centro (no estándar)")
            mappings.append({"target": t.path, "status": "pending" if pending else "mapped",
                             "sources": [_src(f) for f in sources], "ops": ops, "score": s,
                             "reasons": reasons, "issues": list(dict.fromkeys(issues))})
        else:
            best = sorted((p for p in pairs if p[1] == t.path and p[0] > 0.2), key=lambda p: -p[0])[:3]
            mappings.append({
                "target": t.path,
                "status": "pending" if t.required else "no_source",
                "sources": [], "ops": [], "score": None,
                "reasons": ["ningún campo de origen supera el umbral"],
                "issues": ["obligatorio: hay que asignar un origen o un valor por defecto"] if t.required else [],
                "candidates": [{**_src(p[2][0]), "score": p[0]} for p in best],
            })

    unmatched = []
    for f in usable:
        if f.key not in used:
            concept, w = evs[f.key].best()
            unmatched.append({**_src(f), "kind": f.kind, "custom": f.custom,
                              "looks_like": concept if w >= 0.5 else None})

    signature = sorted({(f.entity, f.path, f.dtype) for _, sources, _ in chosen.values() for f in sources})
    return {
        "driver": name or ds.source.rsplit(".", 1)[0],
        "status": "draft",
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "contract": contract.id,
        "source": {"file": ds.source, "format": ds.format, "root": root, "join": join,
                   "signature": [list(s) for s in signature]},
        "score_kind": SCORE_KIND,
        "mappings": mappings,
        "unmatched_sources": unmatched,
    }
