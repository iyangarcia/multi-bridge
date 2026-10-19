"""Domain knowledge the rules matcher uses to recognise what a field means.

Four kinds of evidence, strongest first:
  standard   the field sits at a known HL7 v2 / FHIR position (PID-7, Patient.birthDate)   weight 1.0
  name       a synonym appears in its label/path or in the specific part of its description weight 1.0
  context    a synonym appears only in the general part of the description                 weight 0.5
  values     the values look like it (DNI pattern, "A+", medians of 70 vs 168)             0.35–0.9

Roles matter in healthcare: "apellidos" of the *doctor* (PV1-7.2) is not the
patient's surname. Each field gets a role (patient / practitioner / relative).
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from .model import Field


def words(*texts: str) -> str:
    text = " ".join(t for t in texts if t)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


@dataclass
class Concept:
    hints: list[str]
    hl7: list[str] = field(default_factory=list)    # exact HL7 paths
    fhir: list[str] = field(default_factory=list)   # exact "Resource.path" without slices
    role: str = "patient"                           # practitioner concepts don't get the role penalty


CONCEPTS: dict[str, Concept] = {
    "id_paciente": Concept(["nhc", "n historia", "historia", "num historia", "historia clinica", "mrn", "patient id",
                            "identificador del paciente", "id paciente", "identifier value"],
                           hl7=["PID-3.1", "PID-3", "PID-2"], fhir=["Patient.identifier.value"]),
    "id_tecnico": Concept(["identificador logico", "logical id", "id de secuencia", "id de control"],
                          fhir=["Patient.id"]),
    "dni": Concept(["dni", "nif", "nie", "documento de identidad"], hl7=["PID-19"]),
    "nombre": Concept(["nombre", "nombre de pila", "given", "first name"], hl7=["PID-5.2"],
                      fhir=["Patient.name.given"]),
    "apellidos": Concept(["apellido", "apellidos", "family", "surname", "last name"], hl7=["PID-5.1"],
                         fhir=["Patient.name.family"]),
    "fecha_nacimiento": Concept(["nacimiento", "birth", "birthdate", "dob", "f nac", "fecha nac"], hl7=["PID-7"],
                                fhir=["Patient.birthDate"]),
    "sexo": Concept(["sexo", "gender", "sex", "genero"], hl7=["PID-8"], fhir=["Patient.gender"]),
    "telefono": Concept(["telefono", "phone", "tlf", "movil", "telecom"], hl7=["PID-13"],
                        fhir=["Patient.telecom.value"]),
    "calle": Concept(["calle", "domicilio", "direccion", "street", "address line"], hl7=["PID-11.1"],
                     fhir=["Patient.address.line"]),
    "ciudad": Concept(["ciudad", "city", "localidad", "municipio", "poblacion"], hl7=["PID-11.3"],
                      fhir=["Patient.address.city"]),
    "provincia": Concept(["provincia", "state"], hl7=["PID-11.4"], fhir=["Patient.address.state"]),
    "codigo_postal": Concept(["codigo postal", "cp", "postal", "postal code", "zip"], hl7=["PID-11.5"],
                             fhir=["Patient.address.postalCode"]),
    "pais": Concept(["pais", "country"], hl7=["PID-11.6"], fhir=["Patient.address.country"]),
    "grupo_sanguineo": Concept(["grupo sanguineo", "sangre", "blood", "blood type", "abo", "tipo sangre"]),
    "peso": Concept(["peso", "weight", "body weight"]),
    "altura": Concept(["altura", "talla", "height", "estatura"]),
    "alergia": Concept(["alergia", "alergias", "alergeno", "allergy", "allergen"], hl7=["AL1-3.2", "AL1-3"],
                       fhir=["AllergyIntolerance.code.text"]),
    "medico": Concept(["medico", "doctor", "practitioner", "facultativo", "medico de cabecera", "medico responsable"],
                      hl7=["PV1-7"], fhir=["Patient.generalPractitioner.display"], role="practitioner"),
    "diagnostico": Concept(["diagnostico", "diagnosis", "condition"], hl7=["DG1-3.1", "DG1-4"],
                           fhir=["Condition.code.text", "Condition.code.coding.code"]),
}

ROLES = {
    "practitioner": ["medico", "doctor", "practitioner", "facultativo", "dr", "dra"],
    "relative": ["familiar", "parentesco", "next of kin", "contacto de emergencia"],
}
HL7_ROLE_SEGMENTS = {"PV1-7": "practitioner", "PV1-8": "practitioner", "PV1-17": "practitioner", "NK1": "relative"}
NAME_PARTS = {"nombre", "apellidos"}

DNI = re.compile(r"^(\d{8}|[XYZ]\d{7})[A-Z]$", re.I)
PHONE = re.compile(r"^(\+|00)?\d{9,15}$")
BLOOD = re.compile(r"^(A|B|AB|O|0)\s*(RH)?\s*(\+|-|POS(ITIVO)?|NEG(ATIVO)?)$", re.I)
NUMBER = re.compile(r"^[+-]?\d+([.,]\d+)?$")


@dataclass
class Evidence:
    weights: dict[str, float]
    reasons: dict[str, str]
    kinds: dict[str, str]                 # standard | name | context | values
    role: str = "patient"

    def best(self) -> tuple[str | None, float]:
        if not self.weights:
            return None, 0.0
        k = max(self.weights, key=self.weights.get)
        return k, self.weights[k]


def _flat(values) -> list[str]:
    out = []
    for v in values:
        if isinstance(v, list):
            out += [x for x in v if x]
        elif v not in (None, ""):
            out.append(v)
    return out


def _numbers(flat: list[str]) -> list[float]:
    return [float(v.replace(",", ".")) for v in flat if NUMBER.match(v)]


def _from_values(f: Field, flat: list[str]) -> dict[str, tuple[float, str]]:
    """Guess meaning from the values alone: what a human does with an undocumented Z-segment."""
    if not flat:
        return {}
    found: dict[str, tuple[float, str]] = {}
    share = lambda rx: sum(bool(rx.match(v.strip())) for v in flat) / len(flat)
    if share(DNI) >= 0.8:
        found["dni"] = (0.8, "los valores tienen formato de DNI/NIE")
    if share(BLOOD) >= 0.8:
        found["grupo_sanguineo"] = (0.9, "los valores son grupos sanguíneos (A+, 0-...)")
    if share(PHONE) >= 0.8 and f.dtype in ("string", "integer"):
        found["telefono"] = (0.6, "los valores parecen teléfonos")
    distinct = {v.strip().lower() for v in flat}
    if len(distinct) <= 4 and distinct <= set(SEX_TABLE):
        found["sexo"] = (0.7, "los valores son códigos de sexo")
    if f.dtype == "date":
        years = [int(v[:4]) for v in flat if v[:4].isdigit()]
        if not years:
            years = [int(v[-4:]) for v in flat if v[-4:].isdigit()]
        if years and statistics.median(years) < dt.date.today().year - 2 and min(years) >= 1900:
            found["fecha_nacimiento"] = (0.4, "fechas antiguas: podría ser la fecha de nacimiento")
    nums = _numbers(flat)
    if nums and len(nums) == len(flat) and f.dtype in ("integer", "decimal"):
        med = statistics.median(nums)
        if 30 <= med <= 130 and max(nums) < 300:
            found["peso"] = (0.4, f"números con mediana {med:g}: rango típico de peso en kg")
        if 140 <= med <= 210 and min(nums) >= 40:
            found["altura"] = (0.4, f"números con mediana {med:g}: rango típico de altura en cm")
        if all(re.fullmatch(r"\d{4,5}", v) for v in flat) and 1000 <= med <= 52999:
            found["codigo_postal"] = (0.35, "números de 5 cifras: podría ser un código postal")
    return found


def evidence(f: Field, values) -> Evidence:
    weights: dict[str, float] = {}
    reasons: dict[str, str] = {}
    kinds: dict[str, str] = {}

    def add(concept: str, w: float, why: str, kind: str):
        if w > weights.get(concept, 0):
            weights[concept], reasons[concept], kinds[concept] = w, why, kind

    plain_path = re.sub(r"\[[^\]]*\]", "", f.path)
    for key, c in CONCEPTS.items():
        if f.path in c.hl7 or f"{f.entity}.{plain_path}" in c.fhir:
            add(key, 1.0, f"posición estándar ({f.path if f.path in c.hl7 else f'{f.entity}.{plain_path}'})", "standard")

    desc = f.description or ""
    tail = desc.rsplit(":", 1)[-1] if ":" in desc else desc
    primary = words(f.label, f.path, tail)
    secondary = words(desc)
    for key, c in CONCEPTS.items():
        hit = next((h for h in c.hints if f" {h} " in primary), None)
        if hit:
            add(key, 1.0, f"el nombre contiene «{hit}»", "name")
            continue
        hit = next((h for h in c.hints if f" {h} " in secondary), None)
        if hit:
            add(key, 0.5, f"la descripción menciona «{hit}»", "context")

    for key, (w, why) in _from_values(f, _flat(values)).items():
        add(key, w, why, "values")

    # FHIR "identifier.system" / "telecom.system" describe their neighbour .value; they aren't the data
    if re.search(r"\.(system|use|type)$", f.path):
        weights = {k: round(w * 0.3, 3) for k, w in weights.items()}

    role = "patient"
    everything = words(f.label, f.path, desc)
    for prefix, r in HL7_ROLE_SEGMENTS.items():
        if f.path == prefix or f.path.startswith(prefix + ".") or f.entity == prefix:
            role = r
    for r, hints in ROLES.items():
        if any(f" {h} " in everything for h in hints):
            role = r
    return Evidence(weights, reasons, kinds, role)


def concept_for_name(path: str) -> str | None:
    text = words(path.rsplit(".", 1)[-1], path)
    for key, c in CONCEPTS.items():
        if any(f" {h} " in text for h in c.hints):
            return key
    return None


# --- value translation ---------------------------------------------------------------------------

SEX_TABLE = {"h": "male", "hombre": "male", "varon": "male", "v": "male", "male": "male",
             "mujer": "female", "f": "female", "female": "female",
             "m": None,  # depends on the convention: Spanish H/M (M = mujer) vs English M/F (M = male)
             "o": "other", "otro": "other", "other": "other", "x": "other",
             "u": "unknown", "d": "unknown", "desconocido": "unknown", "unknown": "unknown"}


def sex_map(values: list[str]) -> dict[str, str | None]:
    vals = {v.strip() for v in values}
    lower = {v.lower() for v in vals}
    spanish = bool(lower & {"h", "hombre", "mujer", "varon", "v"})
    english = "f" in lower or "male" in lower
    out = {}
    for v in vals:
        k = v.lower()
        if k == "m":
            out[v] = "female" if spanish and not english else "male" if english and not spanish else None
        else:
            out[v] = SEX_TABLE.get(k)
    return out


def blood_value(v: str) -> str | None:
    m = BLOOD.match(v.strip())
    if not m:
        return None
    abo = "O" if m.group(1).upper() in ("O", "0") else m.group(1).upper()
    rh = "+" if m.group(3).upper().startswith(("+", "POS")) else "-"
    return abo + rh


def translate(concept: str | None, values: list[str]) -> dict[str, str | None]:
    """Source value -> allowed target value for enum targets (None = can't translate, human decides)."""
    if concept == "sexo":
        return sex_map(values)
    if concept == "grupo_sanguineo":
        return {v: blood_value(v) for v in set(values)}
    return {v: None for v in set(values)}
