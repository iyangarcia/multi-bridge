"""Rules proposer: the offline fallback that drafts a recipe when no local model is available.

For every target field it scores every source column on concept evidence from the
destination's domain pack (standard position, name, description, values), role (the record's
subject vs someone else), type and unit; assigns greedily one-to-one; and works out the
transforms. The pack adds its domain's special cases through hooks (packs/__init__.py).
With no pack, names are the evidence. The local Qwen proposer (proposer.py)
produces the same recipe shape.

Scores are hand-weighted rules, NOT probabilities (recipe.CONFIDENCE_KIND).
"""

from __future__ import annotations

import datetime as dt
import re

from . import packs, recipe
from .concepts import Evidence, _flat, evidence, words
from .expected import Expected, Target
from .model import Field
from .records import Rows

THRESHOLD = 0.6
DATE_FORMATS = {"dd/mm/yyyy": "%d/%m/%Y", "dd-mm-yyyy": "%d-%m-%Y", "dd.mm.yyyy": "%d.%m.%Y",
                "yyyymmdd": "%Y%m%d", "yyyymmddHHMM": "%Y%m%d", "yyyymmddHHMMSS": "%Y%m%d", "ISO 8601": "iso"}
UNIT_FACTORS = {("g", "kg"): 0.001, ("lb", "kg"): 0.45359237, ("m", "cm"): 100, ("mm", "cm"): 0.1}
TYPE_OK = {"date": {"date", "datetime"}, "number": {"integer", "decimal"}, "integer": {"integer"},
           "boolean": {"boolean"}}
NAME_MATCH = 0.75   # with no concept for the target, a name this similar is evidence on its own
ENTITY_NAMES = {"nombre", "name", "denominacion", "razon_social"}   # an object's own name ("Cliente" -> cliente.nombre)
MAYBE = 0.4         # with no vocabulary, a column this close is offered as pending, not left as "no data"


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


def _subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _token(a: str, b: str) -> float:
    """How well a column-name word stands for a target-name word: 1 same or a cut ("num" / "numero"),
    0.8 an abbreviation ("dto" / "descuento"), else 0."""
    if a == b or (len(a) >= 3 and b.startswith(a)) or (len(b) >= 3 and a.startswith(b)):
        return 1.0
    if len(a) >= 3 and a[0] == b[0] and len(b) > len(a) + 2 and _subsequence(a, b):
        return 0.8
    return 0.0


def name_match(label: str, t: Target, others: frozenset[str] = frozenset()) -> tuple[float, str | None, str | None]:
    """(score, reason, issue for the reviewer) of a column name against a target with no vocabulary
    behind it, word by word: the target's own name, and the names it sits under ("NIF cliente" for
    cliente.nif, "Num. pedido" for pedido.@numero). An abbreviation, or a column named after the
    object ("Cliente" for cliente.nombre), is a guess: the reviewer decides. So is a column that
    names another object of the destination (`others`: "Fecha entrega" for the order's fecha when
    the destination has an entrega object)."""
    lab = words(label).split()
    lab += ["".join(lab[i:i + 2]) for i in range(len(lab) - 1)]     # "e mail" -> "email"
    leaf = words(t.leaf).split()
    ctx = words(*t.parts[:-1]).split()
    if not lab or not leaf:
        return 0.0, None, None
    best = [max(_token(a, b) for a in lab) for b in leaf]
    words_of_label = words(label).split()
    explained = sum(any(_token(a, b) for b in leaf + ctx) for a in words_of_label) / len(words_of_label)
    if not any(best):
        if t.leaf.lower() in ENTITY_NAMES and ctx and explained == 1:
            return 0.7, f"la columna lleva el nombre de «{' '.join(ctx[-1:])}»",                 f"se toma «{label}» como el {t.leaf} de {ctx[-1]}: revisar"
        return 0.0, None, None
    coverage = sum(best) / len(best)
    s = round(0.5 + 0.3 * coverage + 0.1 * explained, 3)
    abbreviated = [b for b, x in zip(leaf, best) if x == 0.8]
    issue = f"abreviatura en el nombre de la columna («{label}» → {t.leaf}): revisar" if abbreviated else None
    foreign = [a for a in words_of_label if not any(_token(a, b) for b in leaf + ctx)
               and any(_token(a, o) for o in others)]
    if foreign:
        s = round(s - 0.1, 3)
        issue = f"la columna nombra otro objeto del destino («{foreign[0]}»): revisar"
    return s, "mismo nombre" if s >= 0.9 else "nombre casi igual", issue


def other_objects(expected: Expected) -> dict[str, frozenset[str]]:
    """Per target, the words naming the destination's other objects ("entrega" for cliente.email)."""
    objects = {w for t in expected.targets for w in words(*t.parts[:-1]).split()}
    return {t.path: frozenset(objects - set(words(*t.parts).split())) for t in expected.targets}


def score(f: Field, ev: Evidence, t: Target, pack=packs.NONE, others: frozenset[str] = frozenset()
          ) -> tuple[float, list[str]]:
    why: list[str] = []
    w = ev.weights.get(t.concept, 0) if t.concept else 0
    if w:
        s = 0.55 + 0.35 * w + (0.04 if ev.kinds[t.concept] == "standard" else 0)
        why.append(ev.reasons[t.concept])
    else:
        sim = dice(words(f.label).strip(), words(t.leaf).strip())
        by_words, reason, _ = name_match(f.label, t, others) if t.concept is None else (0.0, None, None)
        if t.concept is None and sim >= NAME_MATCH and 0.55 + 0.35 * sim >= by_words:
            s = 0.55 + 0.35 * sim     # no vocabulary knows the target: the name is the evidence
            why.append("mismo nombre" if sim == 1 else "nombre casi igual")
        elif by_words >= THRESHOLD:
            s = by_words
            why.append(reason)
        else:
            s = 0.45 * sim
            if sim > 0.5:
                why.append("nombre parecido")
    ignored = pack.ignored_rivals(t.concept)
    rivals = [v for k, v in ev.weights.items() if k != t.concept and k not in ignored]
    if rivals:
        s -= 0.1 * max(rivals)
    if ev.role != pack.role_of(t.concept):
        s -= 0.35
        why.append(f"pertenece a otra persona ({ev.role})")
    for delta, reason in pack.score_adjust(f, ev, t):
        s += delta
        if reason:
            why.append(reason)
    if f.dtype == "empty":
        s -= 0.5
    elif t.type in TYPE_OK and f.dtype not in TYPE_OK[t.type]:
        s -= 0.3
        why.append(f"tipo incompatible ({f.dtype} → {t.type})")
    if t.unit and f.unit and f.unit != t.unit and (f.unit, t.unit) not in UNIT_FACTORS:
        s -= 0.3
        why.append(f"unidad distinta ({f.unit} → {t.unit})")
    return max(0.0, min(0.99, round(s, 3))), why


def transforms_for(rows: Rows, cols: list[str], t: Target, pack=None) -> tuple[list[dict], list[str], bool]:
    """(transforms, issues, needs_human) to turn these source columns into the target's type and format."""
    pack = pack or packs.NONE
    out: list[dict] = []
    issues: list[str] = []
    pending = False
    f = rows.columns[cols[0]]
    values = [v for c in cols for v in rows.values(c)]
    flat = _flat(values)

    if len(cols) == 1 and (part := pack.part_of(t, evidence(f, rows.values(cols[0]), pack))):
        out.append(part)
        issues.append("se separa el nombre completo: nombre(s) y dos apellidos (revisar nombres compuestos)")
    if len(cols) > 1 and t.multiple != "list":   # a list target takes the values of every column
        out.append({"op": "join_columns", "sep": " "})
    if t.multiple == "list" and (sep := _separator(flat)):
        out.append({"op": "split_values", "sep": sep})
        issues.append(f"varios valores separados por «{sep}» en una celda: uno por elemento")
    if t.type == "date" and f.format in DATE_FORMATS:
        out.append({"op": "date", "from": DATE_FORMATS[f.format]})
    elif t.type == "date" and f.dtype == "integer" and flat and all(_compact_date(v) for v in flat):
        # 19850412 in a format that declares no dates (CSV, Excel, XML): read as yyyymmdd, but say so
        out.append({"op": "date", "from": "%Y%m%d"})
        issues.append("números de 8 cifras leídos como fechas aaaammdd: revisar")
    elif t.type == "date" and f.format == "mixed":
        tried = list(dict.fromkeys(DATE_FORMATS.get(x, "%Y-%m-%d" if x == "yyyy-mm-dd" else None)
                                   for x in f.formats or []))
        if None in tried:
            pending = True
            issues.append(f"formatos de fecha no reconocidos: {', '.join(f.formats)}")
        elif len(tried) == 1:
            out.append({"op": "date", "from": tried[0]})
        else:
            out.append({"op": "date", "from": tried})
            issues.append(f"la columna mezcla formatos de fecha ({', '.join(f.formats)}): se prueban por orden")
    if t.type in ("number", "integer"):
        out.append({"op": "number", "decimal": ","} if f.format == "decimal comma" else {"op": "number"})
        if t.unit and f.unit and (f.unit, t.unit) in UNIT_FACTORS:
            out.append({"op": "scale", "factor": UNIT_FACTORS[(f.unit, t.unit)]})
            issues.append(f"se convierte {f.unit} → {t.unit}")
        elif t.unit and not f.unit and (guess := pack.unit_from_values(flat, t.unit)) \
                and (guess, t.unit) in UNIT_FACTORS:
            out.append({"op": "scale", "factor": UNIT_FACTORS[(guess, t.unit)]})
            issues.append(f"los valores parecen estar en {guess}, no en {t.unit}: se convierten (revisar)")
    if t.enum is not None:
        tr = pack.translate(t.concept, flat, t.enum)
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
    if t.pattern and t.pattern.startswith("\\+") and any(not re.fullmatch(r"\+\d+", v) for v in flat):
        out.append({"op": "phone", "country": "34"})     # also "0034..." and "+34 600 11 22 33"
        if any(not v.startswith(("+", "00")) for v in flat):
            issues.append("números sin prefijo: se asume +34 (España)")
    m = re.fullmatch(r"\[0-9\]\{(\d+)\}", t.pattern or "")
    if m and f.dtype == "integer":
        out.append({"op": "pad", "width": int(m.group(1))})

    if mixed := pack.mixed_column(f):   # different measurements in different records: needs a code filter
        pending = True
        issues.append(mixed)

    if len(cols) == 1 and any(isinstance(v, list) for v in values) and t.multiple != "list":
        # (join_columns already takes one per column; a target that takes a list keeps them all)
        if t.multiple == "join":
            out.append({"op": "join_values", "sep": "; "})
        elif (sep := pack.joins_values(t, f.path)) is not None:
            out.append({"op": "join_values", "sep": sep})        # several values that are one value
        else:
            out.append({"op": "first"})
            issues.append("hay varios valores en origen: se toma el primero")
            if first := pack.first_value_issues(t):
                pending = True
                issues += first
    return out, issues, pending


def _compact_date(v: str) -> bool:
    if not (len(v) == 8 and v.isdigit() and "1900" <= v[:4] <= "2100"):
        return False
    try:
        dt.datetime.strptime(v, "%Y%m%d")
        return True
    except ValueError:
        return False


def _separator(flat: list[str]) -> str | None:
    """The separator of several values written in one cell ("HTA; DLP"), when some cells have one."""
    for sep in (";", "|"):
        if any(sep in v for v in flat):
            return sep
    return None


def evidences(rows: Rows, pack) -> dict[str, Evidence]:
    return {c: evidence(f, rows.values(c), pack) for c, f in rows.columns.items()}


def candidates(rows: Rows, expected: Expected, evs: dict[str, Evidence] | None = None
               ) -> list[tuple[float, str, tuple[str, ...], list[str]]]:
    """Every (score, target, columns, reasons) pair, best first. Also feeds the review screen's dropdowns."""
    pack = packs.get(expected.pack)
    usable = [c for c, f in rows.columns.items() if f.dtype != "empty"]
    evs = evs or evidences(rows, pack)
    multiple = {c: any(isinstance(v, list) for v in rows.values(c)) for c in rows.columns}
    others = other_objects(expected)

    pairs: list[tuple[float, str, tuple[str, ...], list[str]]] = []
    for t in expected.targets:
        for c in usable:
            s, why = score(rows.columns[c], evs[c], t, pack, others[t.path])
            # Prefer one clean value per record: a column with several (two IDs in one field) needs a rule,
            # and a selector column (X [type=Y]) usually gives the clean one. Mostly empty columns lose a
            # little, so a selector that only covers some rows doesn't beat its complete base column.
            if multiple[c] and t.multiple != "join" and pack.joins_values(t, c) is None:
                s -= 0.1
            s = round(s - 0.2 * rows.columns[c].null_ratio, 3)
            pairs.append((s, t.path, (c,), why))
        for s, combo, why in pack.composites(rows, evs, t):
            pairs.append((s, t.path, combo, [why]))
    pairs.sort(key=lambda p: -p[0])
    return pairs


def ranking(rows: Rows, expected: Expected, top: int = 12) -> dict[str, list[dict]]:
    """Per target, the best candidate columns with their score: what a reviewer can switch to."""
    out: dict[str, list[dict]] = {t.path: [] for t in expected.targets}
    for s, target, cols, why in candidates(rows, expected):
        if len(out[target]) < top:
            out[target].append({"from": list(cols), "confidence": s, "why": why})
    return out


def propose(rows: Rows, expected: Expected, name: str | None = None) -> dict:
    pack = packs.get(expected.pack)
    usable = [c for c, f in rows.columns.items() if f.dtype != "empty"]
    evs = evidences(rows, pack)
    pairs = candidates(rows, expected, evs)

    by_path = {t.path: t for t in expected.targets}
    others = other_objects(expected)
    chosen: dict[str, tuple[float, tuple[str, ...], list[str]]] = {}
    used: set[str] = set()
    parts: set[str] = set()     # columns holding several parts (a full name): each part may take one
    for s, target, cols, why in pairs:
        if s < THRESHOLD:
            break
        if target in chosen:
            continue
        split = len(cols) == 1 and pack.part_of(by_path[target], evs[cols[0]]) is not None
        if not used & set(cols) or (split and cols[0] in parts
                                    and not any(chosen[k][1] == cols and pack.part_of(by_path[k], evs[cols[0]])
                                                == pack.part_of(by_path[target], evs[cols[0]]) for k in chosen)):
            chosen[target] = (s, cols, why)
            used |= set(cols)
            if split:
                parts.add(cols[0])

    fields: dict[str, dict] = {}
    for t in expected.targets:
        if t.path in chosen:
            s, cols, why = chosen[t.path]
            transforms, issues, pending = transforms_for(rows, list(cols), t, pack)
            # A near-tie with another free column (home vs mobile phone) is a human's call, not a coin toss.
            rival = next((p for p in pairs if p[1] == t.path and p[2] != cols and not set(p[2]) & set(cols)
                          and not used & (set(p[2]) - set(cols)) and p[0] >= THRESHOLD and s - p[0] < 0.02), None)
            if rival:
                pending = True
                issues.append(f"empate con {' + '.join(rival[2])}: elegir cuál")
            if more := pack.chosen_issues(t, list(cols), evs):
                pending = True
                issues += more
            named = name_match(rows.columns[cols[0]].label, t, others[t.path]) if t.concept is None else None
            if named and len(cols) == 1 and (guess := named[2]) and why == [named[1]]:
                pending = True
                issues.append(guess)
            for c in cols:
                if evs[c].kinds.get(t.concept) == "values":
                    issues.append("deducido solo por los valores: revisar")
                if evs[c].kinds.get(t.concept) == "context" and len(cols) == 1:
                    pending = True    # only a section or a description names it ("Dirección / POBL")
                    issues.append("solo la sección o la descripción lo nombra: revisar")
                if rows.columns[c].custom:
                    issues.append("campo personalizado del centro (no estándar)")
            fields[t.path] = {"status": "pending" if pending else "mapped", "from": list(cols),
                              "transforms": transforms, "confidence": s, "why": why,
                              "issues": list(dict.fromkeys(issues))}
        else:
            best = sorted((p for p in pairs if p[1] == t.path and p[0] > 0.2), key=lambda p: -p[0])[:3]
            issues = ["obligatorio: hay que asignar un origen o un valor por defecto"] if t.required else []
            hints = pack.no_data_issues(rows, usable, t, evs)   # the data may be there, just not usable as is
            free = [p for p in best if p[0] >= MAYBE and not used & set(p[2])]
            if t.concept is None and free:   # no vocabulary: a fair candidate is the reviewer's call, not "no data"
                hints.append(f"quizá {' + '.join(free[0][2])}: revisar")
            issues += hints
            fields[t.path] = {"status": "pending" if t.required or hints else "no_data", "from": [],
                              "transforms": [], "confidence": None,
                              "why": ["ninguna columna de origen supera el umbral"], "issues": issues,
                              "candidates": [{"column": p[2][0], "confidence": p[0]} for p in best]}
    return recipe.new(name or rows.source.rsplit(".", 1)[0], rows, expected, fields, proposed_by="rules")
