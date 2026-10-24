"""The clinical pack: patient records from hospitals (HL7 v2, FHIR, hospital CSV/Excel exports).

Everything the hackathon mapper knew about healthcare lives here: the patient vocabulary
(vocabulary.py), the diagnosis terminology (terms/), LOINC codes, clinical personal data
(NHC, doctor names), and the special cases the hard test files taught us.
"""

from __future__ import annotations

import re
import statistics

from ...concepts import words
from ...selectors import is_selector
from .. import Pack
from .vocabulary import CONCEPTS, HL7_ROLE_SEGMENTS, NAME_PARTS, ROLES, from_values, translate

OBSERVATION_VALUES = {"OBX-5", "valueQuantity.value", "valueString", "valueCodeableConcept.text"}
ICD10 = re.compile(r"^[A-Z]\d{2}(\.[0-9A-Z]{1,4})?$")

SYSTEM = """You map the columns of a hospital data file onto the fields a clinical application expects.
You only see structure: column names, descriptions, types, masked samples (letters become X/x, digits 9),
number summaries (min/median/max) and harmless category values. You never see patient data.

For EVERY target field return one decision:
- "mapped": the source column(s) holding that information. Use two columns only to join the parts
  of one value, in output order (for example a doctor's given name, then family name).
- "no_data": no column holds it. Never force a match just to fill a field.
- "pending": a column might hold it, but a human must decide (ambiguous or conflicting).

Rules:
- Use only column names from the list, exactly as written. Use each column at most once, except a
  full-name column (given name and surnames together): map it to both the given-name and the surname
  targets as "mapped"; the code splits it (given names, then two surnames), you don't have to.
- A patient field never comes from another person's column (doctor, relative, contact).
- Custom fields (HL7 Z-segments, FHIR extensions, unnamed columns) have no documentation: judge them
  by type, number ranges and category values, and say so in "why".
- Observation values (HL7 OBX-5, FHIR Observation.value) hold different measurements in different
  rows; use them only as "pending".
- If a target lists allowed values and the column's values differ (for example H/M vs male/female),
  add "translate" pairs for every source value you can translate.
- "confidence": your honest estimate from 0 to 1. "why": one short sentence in Spanish."""


def is_observation(f) -> bool:
    """A value column shared by every kind of measurement. Selector columns (picked by code) are not."""
    if is_selector(f.path):
        return False
    return f.path in OBSERVATION_VALUES or (f.entity in ("OBX", "Observation") and "value" in f.path.lower())


class Clinical(Pack):
    name = "clinical"
    subject = "patient"
    concepts = CONCEPTS
    roles = ROLES
    role_positions = HL7_ROLE_SEGMENTS
    sensitive = [
        (10, "documento de identidad", ["pid 19"]),
        (20, "identificador del paciente", ["nhc", "historia", "mrn", "identifier", "identificador", "cip",
                                            "tarjeta sanitaria", "pid 3", "pid 2", "pid 18"]),
        (30, "nombre", ["pid 5", "pid 6", "nk1 2"]),
        (40, "contacto", ["pid 13", "pid 14"]),
        (50, "dirección", ["pid 11 1", "pid 11 2"]),
        (60, "fecha de nacimiento", ["pid 7"]),
        (70, "nombre de profesional", ["medico", "doctor", "practitioner", "facultativo", "pv1 7"]),
    ]
    id_reasons = {"identificador del paciente"}
    code_patterns = [("ICD-10", ICD10)]
    code_meanings = {
        # LOINC
        "29463-7": "peso corporal", "3141-9": "peso corporal medido", "8302-2": "altura",
        "8306-3": "altura tumbado", "39156-5": "índice de masa corporal", "8310-5": "temperatura corporal",
        "8867-4": "frecuencia cardiaca", "8480-6": "tensión sistólica", "8462-4": "tensión diastólica",
        "2339-0": "glucosa",
    }
    concept_kind = "clinical_concept"
    system_prompt = SYSTEM

    # -- profiling --------------------------------------------------------------------------------
    def normalizer(self, name=None):
        from .terms import get_normalizer
        return get_normalizer(name or "lexical")

    def not_personal(self, f):
        return re.search(r"^PID-3\.[4-6]$", f.path) is not None   # who issued the ID, ID type

    # -- evidence ---------------------------------------------------------------------------------
    def from_values(self, f, flat):
        return from_values(f, flat)

    def translate(self, concept, values, allowed=None):
        return translate(concept, values, allowed)

    # -- matcher ----------------------------------------------------------------------------------
    def ignored_rivals(self, concept):
        return NAME_PARTS if concept == "medico" else set()   # a doctor's name column is also "a name"

    def score_adjust(self, f, ev, t):
        out = []
        if re.search(r"\[(nickname|old|maiden|anonymous|temp)\]", f.path):
            out.append((-0.2, "uso secundario (apodo, antiguo, temporal)"))   # not the current, official one
        if f.kind == self.concept_kind and t.concept != "diagnostico":
            # the messy Excel's "Diagnóstico principal" (documented as "texto libre del médico") is not a doctor
            out.append((-0.3, "la columna contiene diagnósticos"))
        return out

    def unit_from_values(self, flat, unit):
        """Heights of 1.68 are metres, weights of 65500 are grams, whatever the label says (or doesn't)."""
        nums = [float(v.replace(",", ".")) for v in flat if re.fullmatch(r"[+-]?\d+([.,]\d+)?", v)]
        if not nums or len(nums) < len(flat):
            return None
        med = statistics.median(nums)
        if unit == "cm" and 0.4 <= med <= 2.5:
            return "m"
        if unit == "kg" and 2000 <= med <= 300000:
            return "g"
        return None

    def joins_values(self, t, column):
        return " " if t.concept == "nombre" and column.endswith("given") else None   # FHIR given: ["Lucía", "María"]

    def first_value_issues(self, t):
        if t.concept in ("id_paciente", "dni"):
            # HL7 PID-3 "12345678Z^^^MIR^NI~NHC-30001^^^HALC^MR": the first is the DNI, not the NHC
            return ["varios identificadores en el mismo campo y ningún código de tipo "
                    "(PID-3.5) que los distinga: elegir a mano"]
        return []

    def mixed_column(self, f):
        # OBX-5 / Observation.value hold weight in one row and height in another; the code says which.
        if is_observation(f):
            return ("valor de observación: depende del código (OBX-3 / Observation.code); "
                    "hace falta filtrar por código, aún no soportado")
        return None

    def composites(self, rows, evs, t):
        out = []
        if t.concept == "medico":   # a doctor's name split into given/family (HL7 PV1-7.3 + PV1-7.2)
            people = [c for c, f in rows.columns.items() if evs[c].role == "practitioner" and "." in f.path]
            for given in (c for c in people if evs[c].weights.get("nombre", 0) >= 0.9):
                parent = rows.columns[given].path.rsplit(".", 1)[0]
                family = next((c for c in people if rows.columns[c].entity == rows.columns[given].entity
                               and rows.columns[c].path.rsplit(".", 1)[0] == parent
                               and evs[c].weights.get("apellidos", 0) >= 0.9), None)
                if family:
                    out.append((0.82, (given, family), "nombre y apellidos del médico en columnas separadas: se unen"))
        if t.concept == "apellidos":   # Spanish first and second surname in two columns (APE1 + APE2)
            surnames = [c for c in rows.columns if evs[c].role == self.subject and evs[c].weights.get("apellidos", 0) >= 0.9]
            first = next((c for c in surnames if re.search(r"(1|primer)", words(rows.columns[c].label))), None)
            second = next((c for c in surnames if re.search(r"(2|segundo)", words(rows.columns[c].label))), None)
            if first and second and first != second:
                out.append((0.92, (first, second), "primer y segundo apellido en columnas separadas: se unen"))
        if t.concept == "diagnostico" and t.multiple == "list":   # "Diagnóstico principal" + "Otros diagnósticos"
            dx = sorted((c for c in rows.columns if evs[c].role == self.subject
                         and evs[c].weights.get("diagnostico", 0) >= 0.9), key=lambda c: rows.columns[c].null_ratio)
            if len(dx) > 1:
                out.append((0.9, tuple(dx), "varias columnas de diagnósticos: todas van a la lista"))
        if t.concept == "nombre" and "PID-5.2" in rows.columns and "PID-5.3" in rows.columns:
            out.append((0.95, ("PID-5.2", "PID-5.3"), "nombre de pila + segundo nombre (PID-5.2 + PID-5.3): se unen"))
        return out

    def part_of(self, t, ev):
        # "Nombre completo" / "Nombre y apellidos": given name(s), then two surnames (Spanish convention)
        if t.concept in NAME_PARTS and ev.role == self.subject and all(ev.weights.get(k, 0) >= 0.9 for k in NAME_PARTS):
            return {"op": "name_part", "part": "given" if t.concept == "nombre" else "family", "surnames": 2}
        return None

    def no_data_issues(self, rows, usable, t, evs):
        out = []
        # Weight and height share Observation.value (one row each): their mixed values look like neither,
        # so "no data" would be a silent loss. Any measurement target is pending while such a column exists.
        observation = next((c for c in usable if is_observation(rows.columns[c])), None) if t.unit else None
        if observation:
            out.append(f"el dato puede estar en {observation} (observaciones): hace falta filtrar por código")
        # PID-3 with DNI and NHC as repetitions and no type code: the DNI is there, just not selectable.
        shared_ids = next((c for c in usable if t.concept in ("id_paciente", "dni")
                           and any(isinstance(v, list) for v in rows.values(c))
                           and evs[c].weights.get("id_paciente", 0) >= 0.9), None)
        if shared_ids:
            out.append(f"el dato puede estar en {shared_ids}, que tiene varios identificadores: elegir cuál")
        return out

    # -- AI proposer ------------------------------------------------------------------------------
    def conflict(self, column, f, ev, t, cols, strong):
        """Seen in the evaluation: a full-name column taken as the first name, a diagnosis column taken
        as the doctor."""
        if f.kind == self.concept_kind and t.concept != "diagnostico":
            return f"la columna {column} contiene diagnósticos", strong
        if t.concept in NAME_PARTS and len(cols) == 1 and NAME_PARTS <= strong:
            if self.part_of(t, ev):    # the code splits it (name_part), so it is no conflict
                return None, strong - NAME_PARTS
            return f"la columna {column} tiene nombre y apellidos juntos: hace falta separarlos", strong
        if t.concept == "medico" and ev.role == "practitioner":
            strong = strong - NAME_PARTS
        return None, strong

    def order_columns(self, rows, cols, evidence_of):
        """Joining name parts: given name first, then family name ("Pablo Martinez"), whatever order the
        model chose. Output order is a formatting rule, so the code decides it, not the model."""
        def rank(c: str) -> int:
            ev = evidence_of(c)
            return 0 if ev.weights.get("nombre", 0) >= 0.9 else 1 if ev.weights.get("apellidos", 0) >= 0.9 else 2
        ranks = [rank(c) for c in cols]
        return [c for _, c in sorted(zip(ranks, cols), key=lambda x: x[0])] if {0, 1} <= set(ranks) else cols


CLINICAL = Clinical()
