"""Clinical term normalization (diagnoses today; allergens, drugs, lab tests next).
Part of the clinical pack: `CLINICAL.normalizer()` returns one.

Future normalizers (JEV, an LLM, a SNOMED CT terminology server) implement the
same `normalize()` from base.Normalizer and get registered here. Nothing else
in the codebase needs to change.
"""

from .base import ConceptMatch, Normalizer
from .lexical import LexicalNormalizer

_REGISTRY = {"lexical": LexicalNormalizer}


def get_normalizer(name: str = "lexical") -> Normalizer:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(f"Unknown normalizer {name!r}. Available: {', '.join(_REGISTRY)}") from None


__all__ = ["ConceptMatch", "Normalizer", "LexicalNormalizer", "get_normalizer"]
