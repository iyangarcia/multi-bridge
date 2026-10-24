"""Clinical vocabulary: the concepts a patient record holds, their synonyms and standard positions.

Positions are exact HL7 v2 paths ("PID-7") and FHIR "Resource.path" without slices.
Roles matter in healthcare: "apellidos" of the *doctor* (PV1-7.2) is not the patient's surname.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics

from ...concepts import Concept

CONCEPTS: dict[str, Concept] = {
    "id_paciente": Concept(["nhc", "n historia", "historia", "num historia", "historia clinica", "mrn", "patient id",
                            "identificador del paciente", "id paciente", "identifier value"],
                           ["PID-3.1", "PID-3", "PID-2", "Patient.identifier.value"]),
    "id_tecnico": Concept(["identificador logico", "logical id", "id de secuencia", "id de control"],
                          ["Patient.id"]),
    "dni": Concept(["dni", "nif", "nie", "documento de identidad"], ["PID-19"]),
    "nombre": Concept(["nombre", "nombre de pila", "given", "first name", "given name", "nom"],
                      ["PID-5.2", "Patient.name.given"]),
    "apellidos": Concept(["apellido", "apellidos", "family", "surname", "last name", "ape", "ape1", "ape2",
                           "apellido1", "apellido2", "primer apellido", "segundo apellido",
                           # full-name columns hold the surnames too: the matcher then asks for a split
                           "nombre completo", "full name"], ["PID-5.1", "Patient.name.family"]),
    "fecha_nacimiento": Concept(["nacimiento", "birth", "birthdate", "dob", "f nac", "fecha nac", "fnac",
                                  "date of birth"], ["PID-7", "Patient.birthDate"]),
    "sexo": Concept(["sexo", "gender", "sex", "genero"], ["PID-8", "Patient.gender"]),
    "telefono": Concept(["telefono", "phone", "tlf", "movil", "telecom", "mobile", "cell", "telephone"],
                        ["PID-13", "Patient.telecom.value"]),
    "calle": Concept(["calle", "domicilio", "direccion", "street", "address line", "address", "dom"],
                     ["PID-11.1", "Patient.address.line"]),
    "ciudad": Concept(["ciudad", "city", "localidad", "municipio", "poblacion", "loc", "town"],
                      ["PID-11.3", "Patient.address.city"]),
    "provincia": Concept(["provincia", "state"], ["PID-11.4", "Patient.address.state"]),
    "codigo_postal": Concept(["codigo postal", "cp", "postal", "postal code", "zip"],
                             ["PID-11.5", "Patient.address.postalCode"]),
    "pais": Concept(["pais", "country"], ["PID-11.6", "Patient.address.country"]),
    "grupo_sanguineo": Concept(["grupo sanguineo", "sangre", "blood", "blood type", "abo", "tipo sangre"]),
    "peso": Concept(["peso", "weight", "body weight"]),
    "altura": Concept(["altura", "talla", "height", "estatura"]),
    "alergia": Concept(["alergia", "alergias", "alergeno", "allergy", "allergies", "allergen", "alerg"],
                       ["AL1-3.2", "AL1-3", "AllergyIntolerance.code.text"]),
    "medico": Concept(["medico", "doctor", "practitioner", "facultativo", "medico de cabecera", "medico responsable",
                        "gp", "general practitioner", "family doctor"],
                      ["PV1-7", "Patient.generalPractitioner.display"], role="practitioner"),
    # Not a destination field, but knowing it stops a room number (PV1-3.2) passing for a height.
    "ubicacion": Concept(["ubicacion", "habitacion", "cama", "location", "room", "bed"], ["PV1-3"]),
    "diagnostico": Concept(["diagnostico", "diagnosticos", "diagnosis", "diagnoses", "condition", "conditions",
                            "juicio clinico"],
                           ["DG1-3.1", "DG1-4", "Condition.code.text", "Condition.code.coding.code"]),
}

ROLES = {
    "practitioner": ["medico", "doctor", "practitioner", "facultativo", "dr", "dra", "gp"],
    "relative": ["familiar", "parentesco", "next of kin", "contacto de emergencia"],
}
HL7_ROLE_SEGMENTS = {"PV1-7": "practitioner", "PV1-8": "practitioner", "PV1-17": "practitioner", "NK1": "relative"}
NAME_PARTS = {"nombre", "apellidos"}

DNI = re.compile(r"^(\d{8}|[XYZ]\d{7})[A-Z]$", re.I)
PHONE = re.compile(r"^(\+|00)?\d{9,15}$")
BLOOD = re.compile(r"^(A|B|AB|O|0)\s*(RH)?\s*(\+|-|POS(ITIVO)?|NEG(ATIVO)?)$", re.I)
NUMBER = re.compile(r"^[+-]?\d+([.,]\d+)?$")


def _numbers(flat: list[str]) -> list[float]:
    return [float(v.replace(",", ".")) for v in flat if NUMBER.match(v)]


def from_values(f, flat: list[str]) -> dict[str, tuple[float, str]]:
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


def translate(concept: str | None, values: list[str], allowed: list[str] | None = None) -> dict[str, str | None]:
    """Source value -> allowed target value for enum targets (None = can't translate, human decides).

    Values are first read into a canonical code (male/female..., A+/0-...), then written the way the
    destination's catalogue writes it: "Mujer" if it lists Hombre/Mujer, "female" if male/female."""
    if concept == "sexo":
        out = sex_map(values)
        canon = {item: SEX_TABLE.get(item.strip().lower()) for item in allowed or []}
    elif concept == "grupo_sanguineo":
        out = {v: blood_value(v) for v in set(values)}
        canon = {item: blood_value(item) for item in allowed or []}
    else:
        return {v: None for v in set(values)}
    written = {}
    for c in set(out.values()) - {None}:
        if allowed is None or c in allowed:
            written[c] = c
        else:
            written[c] = next((item for item, ic in canon.items() if ic == c), None)
    return {v: (written.get(c) if c is not None else None) for v, c in out.items()}
