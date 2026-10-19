"""FHIR (Bundle, single resource, list or NDJSON) and plain JSON.

Resources are flattened into dotted paths relative to their resourceType:

    Patient.name[0].family                      -> name.family
    Patient.telecom[system=phone].value         -> telecom[phone].value
    Patient.identifier[system=urn:hule:mrn]     -> identifier[mrn].value
    Patient.extension[url=.../grupo-sanguineo]  -> extension[grupo-sanguineo]   (custom field)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..model import Dataset, Field
from .text import decode

# Short Spanish definitions of the elements hospitals actually send.
# Source: HL7 FHIR R4 resource definitions (paraphrased).
DESCRIPTIONS = {
    "Patient.id": "Identificador lógico del recurso",
    "Patient.identifier.value": "Identificador del paciente (NHC, MRN...)",
    "Patient.identifier.system": "Sistema que asigna el identificador",
    "Patient.name.family": "Apellido(s)",
    "Patient.name.given": "Nombre(s) de pila",
    "Patient.gender": "Sexo administrativo: male | female | other | unknown",
    "Patient.birthDate": "Fecha de nacimiento",
    "Patient.telecom.value": "Dato de contacto (teléfono, email...)",
    "Patient.address.line": "Calle, número, piso",
    "Patient.address.city": "Ciudad / municipio",
    "Patient.address.state": "Provincia / comunidad",
    "Patient.address.postalCode": "Código postal",
    "Patient.address.country": "País",
    "Condition.code.coding.code": "Código del diagnóstico",
    "Condition.code.coding.system": "Terminología del código (CIE-10, SNOMED CT...)",
    "Condition.code.coding.display": "Nombre del diagnóstico según la terminología",
    "Condition.code.text": "Diagnóstico tal como lo escribió el profesional",
    "Condition.clinicalStatus.coding.code": "Estado clínico: active | recurrence | relapse | inactive | remission | resolved",
    "Condition.verificationStatus.coding.code": "Verificación: unconfirmed | provisional | differential | confirmed | refuted",
    "Condition.subject.reference": "Paciente al que pertenece",
    "Condition.onsetDateTime": "Inicio del diagnóstico",
    "AllergyIntolerance.code.text": "Sustancia a la que es alérgico",
    "AllergyIntolerance.code.coding.code": "Código de la sustancia",
    "AllergyIntolerance.criticality": "Criticidad: low | high | unable-to-assess",
    "AllergyIntolerance.patient.reference": "Paciente al que pertenece",
    "Observation.code.coding.code": "Qué se midió (normalmente código LOINC)",
    "Observation.valueQuantity.value": "Valor medido",
    "Observation.valueQuantity.unit": "Unidad del valor",
    "Observation.subject.reference": "Paciente al que pertenece",
    "Observation.effectiveDateTime": "Cuándo se midió",
}

SLICE = re.compile(r"\[[^\]]*\]")


def _slug(url: str) -> str:
    return re.split(r"[/:#]", url.rstrip("/"))[-1] or url


def _put(rec: dict, path: str, value) -> None:
    if value is None or value == "":
        return
    value = value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else (
        ("true" if value else "false") if isinstance(value, bool) else str(value)
    )
    if path not in rec:
        rec[path] = value
    elif isinstance(rec[path], list):
        rec[path].append(value)
    else:
        rec[path] = [rec[path], value]


def _discriminator(path: str, el: dict) -> str | None:
    """FHIR "slicing": tell repeated elements apart by system/use instead of by position."""
    last = path.rsplit(".", 1)[-1]
    if last == "telecom" and el.get("system"):
        return el["system"]
    if last == "identifier" and el.get("system"):
        return _slug(el["system"])
    return None


def _flatten(obj, path: str, rec: dict, custom: dict) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "resourceType" or (k == "text" and isinstance(v, dict) and "div" in v):
                continue
            sub = f"{path}.{k}" if path else k
            if k in ("extension", "modifierExtension") and isinstance(v, list):
                for ext in v:
                    url = ext.get("url", "")
                    epath = f"{sub}[{_slug(url)}]"
                    custom[epath] = f"Extensión propia del centro: {url}"
                    for vk, vv in ext.items():
                        if vk.startswith("value"):
                            if isinstance(vv, dict):
                                _flatten(vv, epath, rec, custom)
                            else:
                                _put(rec, epath, vv)
                        elif vk == "extension":
                            _flatten({"extension": vv}, epath, rec, custom)
            else:
                _flatten(v, sub, rec, custom)
    elif isinstance(obj, list):
        for el in obj:
            if isinstance(el, dict):
                d = _discriminator(path, el)
                _flatten(el, f"{path}[{d}]" if d else path, rec, custom)
            else:
                _put(rec, path, el)
    else:
        _put(rec, path, obj)


def _resources(obj) -> list[dict]:
    if isinstance(obj, list):
        return [r for item in obj for r in _resources(item)]
    if not isinstance(obj, dict):
        return []
    if obj.get("resourceType") == "Bundle":
        return [r for e in obj.get("entry", []) for r in _resources(e.get("resource"))]
    return [obj]


def parse(data: bytes, name: str) -> Dataset:
    text, _ = decode(data)
    stripped = text.strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        obj = [json.loads(l) for l in stripped.splitlines() if l.strip()]  # NDJSON (FHIR bulk export)

    resources = _resources(obj)
    is_fhir = any("resourceType" in r for r in resources)
    ds = Dataset(source=name, format="fhir" if is_fhir else "json")
    if not is_fhir:
        resources = obj if isinstance(obj, list) else [obj]

    custom: dict[str, dict[str, str]] = {}
    for res in resources:
        entity = res.get("resourceType", Path(name).stem) if isinstance(res, dict) else Path(name).stem
        rec: dict = {}
        _flatten(res, "", rec, custom.setdefault(entity, {}))
        ds.tables.setdefault(entity, []).append(rec)

    for entity, records in ds.tables.items():
        paths = list(dict.fromkeys(p for r in records for p in r))
        for p in paths:
            ext = custom[entity].get(p) or next(
                (d for k, d in custom[entity].items() if p.startswith(k + ".")), None
            )
            ds.fields.append(Field(
                entity=entity,
                path=p,
                label=f"{entity}.{p}" if is_fhir else p,
                description=ext or DESCRIPTIONS.get(f"{entity}.{SLICE.sub('', p)}", ""),
                custom=ext is not None,
            ))
    return ds
