"""JSON and FHIR. One reader for both (parsers/fhir.py tells them apart by `resourceType`).

    JSON   one record per object. As a destination: objects nest, a list of objects is a
           repeated group, a list of plain values one target with several values.
    FHIR   one record per Patient, plus the resources that reference it. As a destination, the
           example (a Bundle or one resource) is a template: its data leaves become targets, its
           structural leaves (resourceType, ids, references, systems, codes that say what an
           Observation measures, statuses) are fixed values. Each output item gets its own copy
           of every resource, with new ids and references rewired; a resource whose targets are
           all empty is left out.
"""

from __future__ import annotations

import copy
import json
import re
import uuid

from ..output import EXTRAS, nest
from ..parsers import fhir
from . import Destination, Format, json_bytes

NAMESPACE = uuid.UUID("6f1b1c8e-3b0a-4f43-9a51-6d1e2f3a4b5c")
# Leaves that give a resource its structure, not data (overlay "$targets" can promote one).
FIXED_KEYS = {"resourceType", "id", "fullUrl", "meta", "reference", "system", "use", "url", "status", "intent",
              "request"}
FIXED_SUBTREES = {"clinicalStatus", "verificationStatus", "category", "meta", "request"}
ENUMS = {"Patient.gender": ["male", "female", "other", "unknown"],
         "AllergyIntolerance.criticality": ["low", "high", "unable-to-assess"]}
REQUIRED = {"Observation": ["status", "code"], "Condition": ["subject"], "AllergyIntolerance": ["patient"]}
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _loads(data: bytes):
    text, _ = fhir.decode(data)
    return json.loads(text.strip())


class Json(Format):
    name, label, extensions, mime = "json", "JSON", (".json", ".ndjson"), "application/json"

    def sniff(self, data, name):
        head = data[:64].lstrip(b"\xef\xbb\xbf\x0b \r\n\t")
        return super().sniff(data, name) or head[:1] in (b"{", b"[")

    def read(self, data, name):
        return fhir.parse(data, name)

    def destination(self, data, name, pack, options):
        from ..expected import targets_from_example

        obj = _loads(data)
        first = obj[0] if isinstance(obj, list) and obj else obj
        if isinstance(first, dict) and "resourceType" in first:
            return FHIR.destination(data, name, pack, options)
        return Destination(self.name, targets_from_example(obj, pack), template=obj)

    def blank(self, fields, options):
        from .tabular import _plain
        return Destination(self.name, _plain(fields))   # one key per field, as named (no nesting on dots)

    def write(self, items, expected):
        return json_bytes([nest(item, expected) for item in items])

    def check(self, data: bytes) -> list[str]:
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return [f"no es JSON válido: {e}"]
        if not isinstance(obj, list) or not all(isinstance(r, dict) for r in obj):
            return ["se esperaba una lista de registros (objetos)"]
        return []


def _code(res: dict) -> str | None:
    coding = (res.get("code") or {}).get("coding") or []
    return coding[0].get("code") if coding and isinstance(coding[0], dict) else None


def _fixed(rtype: str, rel: list[str], key: str, parent: str) -> bool:
    if key in FIXED_KEYS or any(seg in FIXED_SUBTREES for seg in rel):
        return True
    if rtype == "Observation" and rel and rel[0] == "code":
        return True    # what the Observation measures: the slice key, not data
    return parent == "valueQuantity" and key in ("unit", "code", "system")


class Fhir(Json):
    name, label, mime = "fhir", "HL7 FHIR", "application/fhir+json"
    joins = True
    blank = Format.blank   # a standard message: its shape comes from an example, not a field list
    keyed_entities = {"Observation": ("code.coding.code", ["valueQuantity.value", "valueQuantity.unit",
                                                           "valueString", "valueCodeableConcept.text"])}
    unit_of = {"valueQuantity.value": "valueQuantity.unit"}

    def sniff(self, data, name):
        return False   # reached through the JSON reader, which sees `resourceType`

    def root(self, ds):
        return "Patient" if "Patient" in ds.tables else super().root(ds)

    def linked(self, ds, root, rec):
        ref = f"{root}/{rec.get('id')}"
        return {e: [r for r in recs if any(k.endswith(".reference") and v == ref for k, v in r.items())]
                for e, recs in ds.tables.items() if e != root}

    # -- destination ------------------------------------------------------------------------------
    def destination(self, data, name, pack, options):
        from ..expected import Target, _type_of

        obj = _loads(data)
        if isinstance(obj, list):
            obj = obj[0]
        bundle = obj if obj.get("resourceType") == "Bundle" else None
        entries = [e for e in bundle.get("entry", []) if isinstance(e, dict) and isinstance(e.get("resource"), dict)] \
            if bundle else [{"resource": obj}]
        if not entries:
            raise ValueError(f"{name}: el ejemplo FHIR no tiene recursos")
        count: dict[str, int] = {}
        for e in entries:
            count[e["resource"]["resourceType"]] = count.get(e["resource"]["resourceType"], 0) + 1
        promote, demote = set(options.get("$targets") or []), set(options.get("$fixed") or [])

        targets, constants, where = [], {}, {}
        for i, e in enumerate(entries):
            res = e["resource"]
            rtype = res["resourceType"]
            key = rtype if count[rtype] == 1 else f"{rtype}[{_code(res) or i}]"
            meaning = pack.code_meanings.get(_code(res) or "") if rtype == "Observation" else None
            display = next(iter((res.get("code") or {}).get("coding") or []), {}).get("display") \
                if rtype == "Observation" else None

            def walk(node, path: str, rel: list[str], pointer: list, parent: str) -> None:
                if isinstance(node, dict):
                    for k, v in node.items():
                        sub, ptr = f"{path}.{k}", pointer + [k]
                        if (_fixed(rtype, rel + [k], k, parent) or sub in demote) and sub not in promote:
                            constants[sub] = v
                        else:
                            walk(v, sub, rel + [k], ptr, k)
                    return
                if isinstance(node, list):
                    if node and all(isinstance(x, dict) for x in node):
                        for j, el in enumerate(node):
                            d = fhir._discriminator(path, el) if len(node) > 1 else None
                            walk(el, f"{path}[{d or j}]" if len(node) > 1 else path, rel, pointer + [j], parent)
                        return
                    first = next((x for x in node if x is not None), None)
                    add(path, rel, pointer, first, wrap=True)
                    return
                add(path, rel, pointer, node, wrap=False)

            def add(path, rel, pointer, value, wrap):
                plain = f"{rtype}." + ".".join(rel)
                typ = _type_of(value)
                if typ == "integer" and rel and rel[-1] == "value":
                    typ = "number"   # FHIR quantities are decimals: an example of 168 doesn't forbid 165.5
                if typ == "string" and isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", value):
                    typ = "date"     # dateTime accepts a plain date
                desc = fhir.DESCRIPTIONS.get(plain, "")
                if rtype == "Observation" and rel and rel[0].startswith("value"):
                    desc = " — ".join(x for x in (desc or "Valor medido", meaning, display) if x)
                unit = None
                if rel[-2:] == ["valueQuantity", "value"]:
                    q = res.get("valueQuantity") or {}
                    unit = str(q.get("code") or q.get("unit") or "").lower() or None
                targets.append(Target(path=path, type=typ, example=value, description=desc, unit=unit,
                                      enum=ENUMS.get(plain)))
                where[path] = (i, pointer, wrap)

            walk(res, key, [], ["resource"], "")
        template = {"bundle": {k: v for k, v in bundle.items() if k not in ("entry", "id", "meta")} if bundle else None,
                    "entries": entries, "where": where}
        return Destination(self.name, targets, template=template, constants=constants)

    # -- writer -----------------------------------------------------------------------------------
    def write(self, items, expected):
        tpl = expected.template
        out_entries = []
        for n, item in enumerate(items):
            fresh = {i: f"urn:uuid:{uuid.uuid5(NAMESPACE, f'{expected.id}:{n}:{i}')}" for i in range(len(tpl['entries']))}
            renamed = {}
            for i, e in enumerate(tpl["entries"]):
                if e.get("fullUrl"):
                    renamed[e["fullUrl"]] = fresh[i]
                if e["resource"].get("id"):
                    renamed[f"{e['resource']['resourceType']}/{e['resource']['id']}"] = fresh[i]
            kept = []
            for i, e in enumerate(tpl["entries"]):
                entry = copy.deepcopy(e)
                mine = [(p, ptr, wrap) for p, (j, ptr, wrap) in tpl["where"].items() if j == i]
                values = {p: item.get(p) for p, _, _ in mine}
                if mine and all(v in (None, []) for v in values.values()):
                    continue      # no data for this resource: leave it out
                for p, ptr, wrap in mine:
                    v = values[p]
                    _put(entry, ptr, None if v in (None, []) else (v if isinstance(v, list) or not wrap else [v]))
                _prune(entry)
                entry["resource"].pop("id", None)
                entry["fullUrl"] = fresh[i]
                _rewire(entry["resource"], renamed)
                kept.append(entry)
            extras = item.get(EXTRAS) or {}
            if extras and kept:
                ext = kept[0]["resource"].setdefault("extension", [])
                for name, v in extras.items():
                    if v not in (None, "", []):
                        ext.append({"url": expected.extension_base + _slug(name),
                                    "valueString": "; ".join(map(str, v)) if isinstance(v, list) else str(v)})
            out_entries += kept
        bundle = copy.deepcopy(tpl["bundle"]) if tpl["bundle"] else {"resourceType": "Bundle", "type": "collection"}
        bundle["entry"] = out_entries
        return json_bytes(bundle)

    # -- checker ----------------------------------------------------------------------------------
    def check(self, data):
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return [f"no es JSON válido: {e}"]
        if not isinstance(obj, dict) or "resourceType" not in obj:
            return ["falta resourceType"]
        problems: list[str] = []
        if obj["resourceType"] == "Bundle":
            entries = obj.get("entry") or []
            urls = [e.get("fullUrl") for e in entries if isinstance(e, dict)]
            if len([u for u in urls if u]) != len({u for u in urls if u}):
                problems.append("fullUrl repetido en el Bundle")
            resources = []
            for n, e in enumerate(entries):
                res = e.get("resource") if isinstance(e, dict) else None
                if not isinstance(res, dict) or "resourceType" not in res:
                    problems.append(f"entrada {n}: sin recurso o sin resourceType")
                else:
                    resources.append((n, res))
            known = {u for u in urls if u}
            for n, res in resources:
                for ref in _references(res):
                    if ref.startswith("urn:uuid:") and ref not in known:
                        problems.append(f"entrada {n}: referencia a un recurso que no está en el Bundle")
        else:
            resources = [(0, obj)]
        for n, res in resources:
            problems += [f"entrada {n} ({res['resourceType']}): {p}" for p in _resource_problems(res)]
        return problems


def _resource_problems(res: dict) -> list[str]:
    out = [f"falta {k}" for k in REQUIRED.get(res["resourceType"], []) if k not in res]
    if res["resourceType"] == "Patient":
        if "gender" in res and res["gender"] not in ENUMS["Patient.gender"]:
            out.append("gender fuera de male | female | other | unknown")
        if "birthDate" in res and not (isinstance(res["birthDate"], str) and DATE.match(res["birthDate"])):
            out.append("birthDate no es una fecha FHIR")
    q = res.get("valueQuantity")
    if isinstance(q, dict) and "value" in q and not isinstance(q["value"], (int, float)):
        out.append("valueQuantity.value no es un número")
    return out


def _references(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reference" and isinstance(v, str):
                yield v
            else:
                yield from _references(v)
    elif isinstance(node, list):
        for v in node:
            yield from _references(v)


def _put(node, pointer: list, value) -> None:
    for p in pointer[:-1]:
        node = node[p]
    node[pointer[-1]] = value


def _prune(node):
    """Remove empty leaves and the containers they leave empty."""
    if isinstance(node, dict):
        for k in list(node):
            if _prune(node[k]):
                del node[k]
        return not node
    if isinstance(node, list):
        node[:] = [x for x in node if not _prune(x)]
        return not node
    return node is None


def _rewire(node, renamed: dict) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reference" and isinstance(v, str) and v in renamed:
                node[k] = renamed[v]
            else:
                _rewire(v, renamed)
    elif isinstance(node, list):
        for v in node:
            _rewire(v, renamed)


def _slug(name: str) -> str:
    from ..concepts import words
    return words(name).strip().replace(" ", "-") or "campo"


JSON, FHIR = Json(), Fhir()
