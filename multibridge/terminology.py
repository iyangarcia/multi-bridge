"""The contract a domain pack's terminology normalizer implements.

A normalizer turns a free-text value into a concept (code + system) or says honestly that it
can't. Profiling uses it to recognise columns of domain terms and to summarise them for the AI
without sending the text (aiview.py). Each pack brings its own (packs/<name>/).
"""

from __future__ import annotations

from typing import Protocol

# Status of a match
MATCHED, AMBIGUOUS, UNKNOWN = "matched", "ambiguous", "unknown"


class Normalizer(Protocol):
    name: str

    def normalize(self, text: str) -> list:
        """Matches with .text, .status, .qualifier, .system. One cell may hold several terms, hence a list."""
        ...
