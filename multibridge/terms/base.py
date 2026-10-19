"""The contract every clinical-term normalizer implements.

Mapping columns is the easy half. The hard half is the *values*: one hospital
writes "DM2 mal controlada", another "Diabetes tipo II", another sends E11.9,
another "sospecha de NAC". A Normalizer turns each of those into a concept
(code + system + qualifier) or says honestly that it can't.

Today's implementation is `LexicalNormalizer` (rules + synonyms, offline).
JEV, an LLM, or a terminology server (Snowstorm/SNOMED CT) plug in by
implementing the same `normalize()` and registering in terms/__init__.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

# Qualifiers: the same disease name means different things clinically.
CONFIRMED, SUSPECTED, HISTORY, FAMILY, NEGATED = "confirmed", "suspected", "history", "family", "negated"
# Status of a match
MATCHED, AMBIGUOUS, UNKNOWN = "matched", "ambiguous", "unknown"


@dataclass
class ConceptMatch:
    text: str                          # the fragment as written in the source
    status: str                        # matched | ambiguous | unknown
    qualifier: str = CONFIRMED
    code: str | None = None
    display: str | None = None
    system: str | None = None
    method: str | None = None          # code | exact | abbreviation | fuzzy
    similarity: float | None = None    # string similarity for fuzzy hits. NOT a calibrated probability.
    alternatives: list[tuple[str | None, str]] = field(default_factory=list)  # (code, display) when ambiguous
    modifiers: list[str] = field(default_factory=list)  # "mal controlada", "reagudizada"...
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Normalizer(Protocol):
    name: str

    def normalize(self, text: str) -> list[ConceptMatch]:
        """One cell may hold several diagnoses ("AP de IAM; HTA"), hence a list."""
        ...
