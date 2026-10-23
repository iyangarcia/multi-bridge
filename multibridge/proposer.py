"""The AI proposer: a local Qwen model drafts the recipe; the rules matcher is the fallback.

Division of labour:
    the model decides   which column(s) hold each target field, or that none does
                        ("mapped" / "no_data" / "pending"), with a confidence and a one-line reason,
                        plus value translations the rules can't make
    the code decides    the format conversions (date patterns, decimal commas, padding, title case),
                        from the profile, which knows them exactly (matcher.transforms_for)

The model only sees aiview.source_view / target_view: structure, masked samples, number
summaries, harmless categories (COMPLIANCE C4, C6). Its reply is constrained by a JSON schema
listing the real columns, then checked again here: no invented columns, no column used twice,
no translations outside the allowed values, no required field left as "no_data" (C7).

Two passes (ROADMAP D6): first with thinking off; then the doubtful fields again with thinking on.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import matcher, packs, recipe
from .ai import ollama
from .aiview import source_view, target_view
from .concepts import _flat, evidence
from .expected import Expected
from .model import is_metadata
from .records import Rows

DEFAULT_MODEL = "qwen3:8b"
DOUBTFUL = 0.7
MAX_EXAMPLES = 3

SYSTEM = """You map the columns of a data file onto the fields an application expects.
You only see structure: column names, descriptions, types, masked samples (letters become X/x, digits 9),
number summaries (min/median/max) and harmless category values. You never see the real data.

For EVERY target field return one decision:
- "mapped": the source column(s) holding that information. Use two columns only to join the parts
  of one value, in output order (for example a given name, then a family name).
- "no_data": no column holds it. Never force a match just to fill a field.
- "pending": a column might hold it, but a human must decide (ambiguous or conflicting).

Rules:
- Use only column names from the list, exactly as written. Use each column at most once.
- A field about the record's subject never comes from a column about someone else.
- Custom fields (extensions, unnamed columns) have no documentation: judge them by type, number
  ranges and category values, and say so in "why".
- If a target lists allowed values and the column's values differ (for example Y/N vs true/false),
  add "translate" pairs for every source value you can translate.
- "confidence": your honest estimate from 0 to 1. "why": one short sentence in Spanish."""


def system_prompt(expected: Expected) -> str:
    """The destination's domain pack may say how to read files of its domain."""
    return packs.get(expected.pack).system_prompt or SYSTEM


def schema(targets: list[str], columns: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"fields": {"type": "array", "minItems": len(targets), "maxItems": len(targets), "items": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": targets},
                "status": {"type": "string", "enum": ["mapped", "no_data", "pending"]},
                "from": {"type": "array", "items": {"type": "string", "enum": columns}, "maxItems": 3},
                "translate": {"type": "array", "items": {
                    "type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
                    "required": ["source", "target"]}},
                "confidence": {"type": "number"},
                "why": {"type": "string"},
            },
            "required": ["target", "status", "from", "confidence", "why"],
        }}},
        "required": ["fields"],
    }


def examples_from(folder: str | Path | None, expected: Expected) -> list[dict]:
    """Approved recipes for the same destination become worked examples (per-company learning, no retraining)."""
    if not folder or not Path(folder).is_dir():
        return []
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            r = recipe.load(p)
            recipe.verify(r)
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if r["expected"] != expected.id:
            continue
        described = r["source"].get("described", {})
        out.append({"format": r["source"]["format"], "decisions": [
            {"target": t, "status": f["status"], "from": [{"column": c, "described_as": described.get(c, c)}
                                                         for c in f["from"]]}
            for t, f in r["fields"].items()]})
    return out[:MAX_EXAMPLES]


def _prompt(rows: Rows, expected: Expected, examples: list[dict], only: list[str] | None = None) -> str:
    targets = [t for t in target_view(expected) if only is None or t["target"] in only]
    source = source_view(rows)
    keep = set(offered(rows))
    source["columns"] = [c for c in source["columns"] if c["column"] in keep]
    body = {"targets": targets, "source": source}
    if examples:
        body["approved_examples_from_other_files"] = examples
    return json.dumps(body, ensure_ascii=False)


def offered(rows: Rows) -> list[str]:
    """Columns the model may choose from. Metadata (identifier.system, telecom.use...) only describes
    its neighbour .value; qwen3:8b used it to invent fields that have no source, so it is never offered."""
    return [c for c, f in rows.columns.items()
            if f.dtype != "empty" and not is_metadata(f.path)]


def _conflict(rows: Rows, cols: list[str], t, pack) -> str | None:
    """Does a chosen column clearly mean something else? A cross-check of the model against the rules.

    Seen in the evaluation: a technical `id` taken as the record's identifier; the pack adds its
    domain's cases. All become pending.
    """
    if not t.concept:
        return None
    for c in cols:
        f = rows.columns[c]
        ev = evidence(f, rows.values(c), pack)
        strong = {k for k, w in ev.weights.items() if w >= 0.9 and ev.kinds.get(k) in ("standard", "name")}
        standard = {k for k in strong if ev.kinds.get(k) == "standard"}
        if standard:  # a known standard position outranks a name that happens to match (a technical "id")
            strong = standard
        why, strong = pack.conflict(c, f, ev, t, cols, strong)
        if why:
            return why
        if strong and t.concept not in strong:
            return f"la columna {c} parece ser {', '.join(sorted(strong))}, no {t.concept}"
    return None


def _fields_from_answer(answer: dict, rows: Rows, expected: Expected, model: str,
                        only: list[str] | None = None, taken: dict[str, str] | None = None,
                        rules: dict | None = None) -> dict[str, dict]:
    """Check the model's reply and turn it into recipe fields. Anything dubious becomes 'pending'."""
    pack = packs.get(expected.pack)
    wanted = [t for t in expected.targets if only is None or t.path in only]
    allowed = set(offered(rows))
    by_target: dict[str, dict] = {}
    for item in answer.get("fields", []) if isinstance(answer, dict) else []:
        if isinstance(item, dict) and item.get("target") in {t.path for t in wanted}:
            by_target.setdefault(item["target"], item)

    used = dict(taken or {})
    fields: dict[str, dict] = {}
    order = sorted(wanted, key=lambda t: -float(by_target.get(t.path, {}).get("confidence") or 0))
    for t in order:
        item = by_target.get(t.path)
        issues: list[str] = []
        if item is None:
            fields[t.path] = {"status": "pending", "from": [], "transforms": [], "confidence": None,
                              "why": [], "issues": ["el modelo no respondió este campo"], "proposed_by": model}
            continue
        status = item.get("status") if item.get("status") in recipe.STATUSES else "pending"
        cols = [c for c in item.get("from") or [] if isinstance(c, str)]
        unknown = [c for c in cols if c not in allowed]
        if unknown:
            issues.append(f"el modelo citó columnas que no existen o no se ofrecen: {', '.join(unknown)}")
            cols = [c for c in cols if c in allowed]
        if len(set(cols)) < len(cols):
            issues.append("el modelo repitió la misma columna")
            status, cols = "pending", []
        clash = [c for c in cols if c in used]
        if clash:
            issues.append(f"columna ya usada por {used[clash[0]]}: {', '.join(clash)}")
            status, cols = "pending", []
        try:
            confidence = max(0.0, min(1.0, round(float(item.get("confidence")), 2)))
        except (TypeError, ValueError):
            confidence = None
        if status == "mapped" and not cols:
            status = "pending"
            issues.append("marcado como mapeado sin columna de origen")
        if status == "no_data" and t.required:
            status = "pending"
            issues.append("obligatorio: el modelo no encontró origen; hay que decidir")
        if status == "no_data" and rules:
            suggestion = rules["fields"].get(t.path, {})
            if suggestion.get("status") == "mapped" and (suggestion.get("confidence") or 0) >= 0.85:
                status = "pending"
                issues.append(f"el modelo dice que no hay dato, pero las reglas sugieren {' + '.join(suggestion['from'])}")
        if cols and (conflict := _conflict(rows, cols, t, pack)):
            issues.append(f"{conflict}: revisar")
            status = "pending"

        transforms: list[dict] = []
        if len(cols) > 1:   # output order is a formatting rule, so the code decides it, not the model
            cols = pack.order_columns(rows, cols, lambda c: evidence(rows.columns[c], rows.values(c), pack))
        if cols:
            transforms, rule_issues, needs_human = matcher.transforms_for(rows, cols, t, pack)
            issues += rule_issues
            if t.enum is not None:
                transforms, issues, needs_human = _merge_translations(rows, cols, t, item, transforms, issues,
                                                                      needs_human, pack)
            if needs_human:
                status = "pending"
            if any(rows.columns[c].custom for c in cols):
                issues.append("campo personalizado del centro (no estándar)")
            used.update({c: t.path for c in cols})
        fields[t.path] = {"status": status, "from": cols, "transforms": transforms, "confidence": confidence,
                          "why": [str(item.get("why", ""))[:300]] if item.get("why") else [],
                          "issues": list(dict.fromkeys(issues)), "proposed_by": model}
    return {t.path: fields[t.path] for t in wanted}


def _merge_translations(rows, cols, t, item, transforms, issues, needs_human, pack):
    """Use the model's translations only for values the rules couldn't translate, and only into allowed values."""
    flat = set(_flat(rows.values(cols[0])))
    proposed = {p.get("source"): p.get("target") for p in item.get("translate") or [] if isinstance(p, dict)}
    rule_map = next((x["values"] for x in transforms if x["op"] == "translate"), {})
    missing = sorted(v for v in flat if rule_map.get(v, v) not in t.enum)
    if not missing:
        return transforms, issues, needs_human
    accepted = {v: proposed[v] for v in missing if proposed.get(v) in t.enum}
    rejected = [v for v in missing if v not in accepted]
    if accepted:
        merged = {**rule_map, **accepted}
        transforms = [x for x in transforms if x["op"] != "translate"]
        transforms.insert(0, {"op": "translate", "values": dict(sorted(merged.items()))})
        issues = [i for i in issues if not i.startswith("valores sin traducción")]
        issues.append(f"traducción propuesta por la IA: {', '.join(f'{k}→{v}' for k, v in accepted.items())} (revisar)")
    if rejected:
        issues.append(f"valores sin traducción al catálogo: {', '.join(rejected)}")
    mixed = pack.mixed_column(rows.columns[cols[0]]) is not None
    return transforms, issues, bool(rejected) or mixed


def propose_ai(rows: Rows, expected: Expected, model: str = DEFAULT_MODEL, name: str | None = None,
               examples: list[dict] | None = None, chat=None, second_pass: bool = True) -> dict:
    chat = chat or ollama.chat
    columns = offered(rows)
    rules = matcher.propose(rows, expected)  # cross-check only: never copied silently
    targets = [t.path for t in expected.targets]
    started = time.monotonic()
    system = system_prompt(expected)
    answer = chat(model, system, _prompt(rows, expected, examples or []), schema=schema(targets, columns), think=False)
    fields = _fields_from_answer(answer, rows, expected, model, rules=rules)

    retried: list[str] = []
    if second_pass:
        doubtful = [t for t, f in fields.items()
                    if f["status"] == "pending" or (f["confidence"] is not None and f["confidence"] < DOUBTFUL)]
        if doubtful:
            taken = {c: t for t, f in fields.items() if t not in doubtful for c in f["from"]}
            free = [c for c in columns if c not in taken]
            again = chat(model, system, _prompt(rows, expected, examples or [], only=doubtful),
                         schema=schema(doubtful, free or columns), think=True)
            for t, f in _fields_from_answer(again, rows, expected, f"{model} (think)", only=doubtful, rules=rules,
                                            taken=taken).items():
                if f["status"] != "pending" or not fields[t]["from"]:
                    fields[t] = f
            retried = doubtful

    draft = recipe.new(name or rows.source.rsplit(".", 1)[0], rows, expected, fields, proposed_by=model)
    draft["proposer"] = {"model": model, "seconds": round(time.monotonic() - started, 1),
                         "second_pass": retried}
    return draft


def propose(rows: Rows, expected: Expected, model: str = "auto", name: str | None = None,
            recipes_dir: str | Path | None = None, second_pass: bool = True) -> dict:
    """`model`: "rules", a local Ollama model name, or "auto" (the default local model, rules if it's not there)."""
    if model == "rules":
        draft = matcher.propose(rows, expected, name)
        draft["proposer"] = {"model": "rules"}
        return draft
    chosen = DEFAULT_MODEL if model == "auto" else model
    try:
        draft = propose_ai(rows, expected, chosen, name, examples_from(recipes_dir, expected),
                           second_pass=second_pass)
    except ollama.OllamaUnavailable as e:
        if model != "auto":
            raise
        draft = matcher.propose(rows, expected, name)
        draft["proposer"] = {"model": "rules", "fallback_reason": str(e)}
    finally:
        ollama.unload(chosen)
    return draft
