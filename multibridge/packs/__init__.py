"""Domain packs: what a domain's data *means* (ROADMAP D11). The core knows formats and structure only.

A pack is optional. It brings:

    concepts / roles        vocabulary and synonyms for recognising fields, and who a field belongs to
    sensitive               field-name hints for personal data of that domain (on top of the core's)
    code_patterns           value shapes that are codes of the domain's terminologies
    code_meanings           words for the codes the domain uses (selector descriptions)
    normalizer()            a terminology normalizer for free-text terms (terminology.py)
    from_values / translate value detectors and value translations into allowed values
    matcher / proposer hooks the domain's special cases (methods below, all no-ops here)
    system_prompt           how the AI proposer should read files of this domain

Which pack a destination uses is declared in its overlay (`"$pack": "clinical"` in
`<name>.rules.json`). Without one, matching relies on names, profiles and the AI.

Profiling always runs the detectors of every installed pack: before the destination is known,
it is safer to over-detect personal data than to miss it (COMPLIANCE, D15).
"""

from __future__ import annotations

import re

from ..concepts import SUBJECT, Concept


class Pack:
    name = "none"
    subject = SUBJECT                             # name of the role of the record's own subject
    concepts: dict[str, Concept] = {}
    roles: dict[str, list[str]] = {}              # role -> words that mark it
    role_positions: dict[str, str] = {}           # path or entity prefix -> role
    sensitive: list[tuple[int, str, list[str]]] = []   # (rank, reason, name hints); lower rank wins
    id_reasons: set[str] = set()                  # sensitive reasons that make a column an identifier
    code_patterns: list[tuple[str, re.Pattern]] = []   # (format label, value regex)
    code_meanings: dict[str, str] = {}
    concept_kind = "concept"                      # Field.kind of a column of recognised terms
    system_prompt: str | None = None

    # -- profiling --------------------------------------------------------------------------------
    def normalizer(self, name: str | None = None):
        return None

    def not_personal(self, f) -> bool:
        """Metadata next to a personal value (who issued an ID, its type), not personal data itself."""
        return False

    # -- evidence ---------------------------------------------------------------------------------
    def from_values(self, f, flat: list[str]) -> dict[str, tuple[float, str]]:
        """Guess concepts from the values alone: {concept: (weight, reason)}."""
        return {}

    def translate(self, concept: str | None, values: list[str], allowed: list[str] | None = None
                  ) -> dict[str, str | None]:
        """Source value -> one of the `allowed` target values (None = can't translate, a human decides)."""
        return {v: None for v in set(values)}

    def role_of(self, concept: str | None) -> str:
        return (self.concepts[concept].role if concept in self.concepts else None) or self.subject

    # -- matcher ----------------------------------------------------------------------------------
    def ignored_rivals(self, concept: str | None) -> set[str]:
        """Other concepts a column may also show without counting against this target."""
        return set()

    def score_adjust(self, f, ev, t) -> list[tuple[float, str | None]]:
        """Extra (score delta, reason) for a column against a target."""
        return []

    def unit_from_values(self, flat: list[str], unit: str) -> str | None:
        """The unit the values are really in, when the label doesn't say."""
        return None

    def joins_values(self, t, column: str) -> str | None:
        """Separator when several values in one cell are one value (not a choice), else None."""
        return None

    def first_value_issues(self, t) -> list[str]:
        """Taking the first of several values is not acceptable for this target: why (makes it pending)."""
        return []

    def mixed_column(self, f) -> str | None:
        """A column holding different measurements in different records: why it can't be used as is."""
        return None

    def composites(self, rows, evs, t) -> list[tuple[float, tuple[str, ...], str]]:
        """Values split over several columns that must be joined: (score, columns in output order, reason)."""
        return []

    def part_of(self, t, ev) -> dict | None:
        """The transform that takes this target's part out of a column holding several parts (a full
        name -> given name / surnames), else None. Such a column may feed every one of its parts."""
        return None

    def chosen_issues(self, t, cols, evs) -> list[str]:
        """Problems with the chosen columns that need a human (makes the field pending)."""
        return []

    def no_data_issues(self, rows, usable, t, evs) -> list[str]:
        """Why "no data" may be a silent loss for this target (makes the field pending)."""
        return []

    # -- AI proposer ------------------------------------------------------------------------------
    def conflict(self, column: str, f, ev, t, cols: list[str], strong: set[str]) -> tuple[str | None, set[str]]:
        """Cross-check of the model: (why this column clearly means something else, or None; strong concepts)."""
        return None, strong

    def order_columns(self, rows, cols: list[str], evidence_of) -> list[str]:
        """Output order when joining columns."""
        return cols


NONE = Pack()


def _installed() -> dict[str, Pack]:
    from .clinical import CLINICAL
    return {CLINICAL.name: CLINICAL}


def get(name: str | None) -> Pack:
    if not name:
        return NONE
    packs = _installed()
    try:
        return packs[name]
    except KeyError:
        raise ValueError(f"pack desconocido {name!r}. Instalados: {', '.join(packs)}") from None


def installed() -> list[Pack]:
    return list(_installed().values())
