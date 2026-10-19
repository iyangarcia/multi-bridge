"""Offline rule-based normalizer: synonyms, abbreviations, qualifiers, typos.

Pipeline for each fragment of a cell:
  1. split the cell into fragments        "AP de IAM; HTA"         -> "AP de IAM", "HTA"
  2. code?                                "E11.9"                  -> E11 (subcode)
  3. qualifier                            "sospecha de NAC"        -> suspected + "nac"
  4. strip clinical modifiers             "DM2 mal controlada"     -> "dm2" + ["mal controlada"]
  5. exact synonym / abbreviation         "hta"                    -> I10
  6. ambiguous abbreviation               "IRA"                    -> N17 or J96.0, ask a human
  7. term inside a longer phrase          "paciente con epoc"      -> J44
  8. fuzzy (typos)                        "diabetis tipo 2"        -> E11, similarity 0.93
  9. otherwise unknown                    "DiabA"                  -> ask the centre what it means
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from . import seed_es
from .base import (AMBIGUOUS, CONFIRMED, FAMILY, HISTORY, MATCHED, NEGATED, SUSPECTED, UNKNOWN,
                   ConceptMatch)

CODE = re.compile(r"^([A-Z]\d{2}(?:\.[0-9A-Z]{1,4})?)(?:\s+(.*))?$")
SNOMED = re.compile(r"^\d{6,18}$")
LOINC = re.compile(r"^\d{1,5}-\d$")

# Checked in this order, against the normalised text.
PREFIX_QUALIFIERS = [
    (FAMILY, ["antecedentes familiares de", "antecedente familiar de", "af de", "madre con", "padre con",
              "hermano con", "hermana con"]),
    (HISTORY, ["antecedentes personales de", "antecedentes de", "antecedente de", "ap de", "ap", "historia de",
               "hx de", "hx"]),
    (SUSPECTED, ["sospecha de", "sospecha", "sosp de", "sosp", "probable", "posible", "a descartar", "descartar",
                 "dd"]),
    (NEGATED, ["negativo para", "no", "niega", "sin"]),
]
SUFFIX_QUALIFIERS = [
    (NEGATED, ["descartada", "descartado", "negativo", "negativa"]),
    (SUSPECTED, ["a descartar", "probable", "a estudio", "en estudio"]),
    (HISTORY, ["resuelta", "resuelto", "previa", "previo", "antigua", "antiguo"]),
]
PREFIX_MODIFIERS = ["reagudizacion de", "descompensacion de", "exacerbacion de", "agudizacion de"]
SUFFIX_MODIFIERS = ["mal controlada", "mal controlado", "bien controlada", "bien controlado", "reagudizada",
                    "reagudizado", "descompensada", "descompensado", "de larga evolucion", "en tratamiento",
                    "leve", "moderada", "moderado", "grave", "severa", "severo", "conocida", "conocido", "estable",
                    # ICD-style fillers: "Sepsis, no especificada", "Neumonía, organismo no especificado"
                    "organismo no especificado", "no especificada", "no especificado", "sin especificar",
                    "sin otra especificacion"]

FUZZY_MIN = 0.85


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def split_fragments(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[;\n+/]|,", text) if p.strip()]
    merged: list[str] = []
    for p in parts:  # "DM2, mal controlada" -> one fragment
        if merged and norm(p) in SUFFIX_MODIFIERS:
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    return merged


class LexicalNormalizer:
    name = "lexical"

    def __init__(self, concepts=seed_es.CONCEPTS, abbreviations=seed_es.ABBREVIATIONS,
                 ambiguous=seed_es.AMBIGUOUS, system=seed_es.SYSTEM):
        self.concepts = concepts
        self.system = system
        self.synonyms = {norm(s): code for code, (_, syns) in concepts.items() for s in syns}
        self.abbreviations = {norm(k): v for k, v in abbreviations.items()}
        self.ambiguous = {norm(k): v for k, v in ambiguous.items()}

    # -- public -------------------------------------------------------------------------------
    def normalize(self, text: str) -> list[ConceptMatch]:
        out: list[ConceptMatch] = []
        for frag in split_fragments(str(text)):
            # "DM2 e HTA" is two diagnoses, "insuficiencia cardiaca y renal" is not: split only if every part resolves
            if re.search(r"\s(y|e)\s", frag, re.I):
                subs = [self._one(s) for s in re.split(r"\s(?:y|e)\s", frag, flags=re.I)]
                if all(s.status != UNKNOWN for s in subs):
                    out += subs
                    continue
            out.append(self._one(frag))
        return out

    # -- internals ----------------------------------------------------------------------------
    def _match(self, text, code, method, qualifier, modifiers, similarity=None, note=None) -> ConceptMatch:
        display = self.concepts.get(code, (None,))[0]
        if display is None and code[:3] in self.concepts:
            display = self.concepts[code[:3]][0]
            note = note or f"Subcódigo de {code[:3]}"
        return ConceptMatch(text=text, status=MATCHED, qualifier=qualifier, code=code, display=display,
                            system=self.system, method=method, similarity=similarity, modifiers=modifiers,
                            note=note)

    def _one(self, original: str) -> ConceptMatch:
        original = original.strip()
        qualifier = SUSPECTED if "?" in original else CONFIRMED

        code_match = CODE.match(original.upper())
        if code_match:
            code = code_match.group(1)
            if code in self.concepts or code[:3] in self.concepts:
                return self._match(original, code, "code", qualifier, [])
            return ConceptMatch(text=original, status=UNKNOWN, code=code, system=self.system, method="code",
                                note="Formato CIE-10 válido, pero no está en la terminología cargada")
        if SNOMED.match(original):
            return ConceptMatch(text=original, status=UNKNOWN, note="Parece un código SNOMED CT: conecta un servidor de terminología")
        if LOINC.match(original):
            return ConceptMatch(text=original, status=UNKNOWN, note="Parece un código LOINC (una prueba, no un diagnóstico)")

        t = norm(original)
        qualifier, t = self._qualifier(t, qualifier)
        modifiers, t = self._modifiers(t)

        if t in self.synonyms:
            return self._match(original, self.synonyms[t], "exact", qualifier, modifiers)
        if t in self.abbreviations:
            return self._match(original, self.abbreviations[t], "abbreviation", qualifier, modifiers)
        if t in self.ambiguous:
            return self._ambiguous(original, qualifier, modifiers, self.ambiguous[t],
                                   f"'{t.upper()}' significa cosas distintas según el servicio: confirmar con el centro")

        contained = self._contained(t)
        if len(contained) == 1:
            return self._match(original, contained[0], "contains", qualifier, modifiers,
                               note="Término reconocido dentro de un texto más largo")
        if len(contained) > 1:
            return self._ambiguous(original, qualifier, modifiers,
                                   [(c, self.concepts[c][0]) for c in contained],
                                   "El texto menciona varios diagnósticos")

        if len(t) >= 5:
            scored = sorted(((SequenceMatcher(None, t, s).ratio(), c) for s, c in self.synonyms.items()),
                            reverse=True)
            best, code = scored[0]
            if best >= FUZZY_MIN:
                rival = next(((r, c) for r, c in scored[1:] if c != code), (0, None))
                if best - rival[0] < 0.03:
                    return self._ambiguous(original, qualifier, modifiers,
                                           [(code, self.concepts[code][0]), (rival[1], self.concepts[rival[1]][0])],
                                           "Dos diagnósticos se parecen casi igual al texto")
                return self._match(original, code, "fuzzy", qualifier, modifiers, similarity=round(best, 2),
                                   note="Coincidencia aproximada (¿errata?): revisar")

        note = ("Posible abreviatura local desconocida: pedir aclaración al centro"
                if " " not in t and len(t) <= 6 else "Sin correspondencia en la terminología cargada")
        return ConceptMatch(text=original, status=UNKNOWN, qualifier=qualifier, modifiers=modifiers, note=note)

    def _ambiguous(self, original, qualifier, modifiers, alternatives, note) -> ConceptMatch:
        return ConceptMatch(text=original, status=AMBIGUOUS, qualifier=qualifier, system=self.system,
                            alternatives=alternatives, modifiers=modifiers, note=note)

    @staticmethod
    def _qualifier(t: str, qualifier: str) -> tuple[str, str]:
        for q, prefixes in PREFIX_QUALIFIERS:
            for p in prefixes:
                if t.startswith(p + " "):
                    return q, t[len(p) + 1:]
        for q, suffixes in SUFFIX_QUALIFIERS:
            for s in suffixes:
                if t.endswith(" " + s):
                    return q, t[: -len(s) - 1]
        return qualifier, t

    @staticmethod
    def _modifiers(t: str) -> tuple[list[str], str]:
        found, changed = [], True
        while changed:
            changed = False
            for p in PREFIX_MODIFIERS:
                if t.startswith(p + " "):
                    found.append(p)
                    t, changed = t[len(p) + 1:], True
            for s in SUFFIX_MODIFIERS:
                if t.endswith(" " + s):
                    found.append(s)
                    t, changed = t[: -len(s) - 1], True
        return found, t

    def _contained(self, t: str) -> list[str]:
        padded = f" {t} "
        hits = [(s, c) for s, c in self.synonyms.items() if f" {s} " in padded]
        hits += [(a, c) for a, c in self.abbreviations.items() if f" {a} " in padded]
        # keep the longest phrase when one hit is part of another ("hipertension" inside "hipertension arterial")
        hits = [(s, c) for s, c in hits if not any(s != o and f" {s} " in f" {o} " for o, _ in hits)]
        return list(dict.fromkeys(c for _, c in hits))
