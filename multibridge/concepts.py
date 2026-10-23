"""Evidence for what a field means, from a domain pack's vocabulary (packs/).

Four kinds of evidence, strongest first:
  standard   the field sits at a position a standard defines for the concept              weight 1.0
  name       a synonym appears in its label/path or in the specific part of its description weight 1.0
  context    a synonym appears only in the general part of the description                 weight 0.5
  values     the values look like it (the pack's value detectors)                          0.35–0.9

Roles: a field may belong to someone other than the record's subject (a contact person's surname
is not the customer's). The pack says which words and positions mark another role.

With no pack there is no vocabulary: every Evidence is empty and the matcher falls back to names.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .model import Field, is_metadata

SUBJECT = "subject"   # default name of the record's own subject role; a pack may rename it


def words(*texts: str) -> str:
    text = " ".join(t for t in texts if t)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


@dataclass
class Concept:
    hints: list[str]
    positions: list[str] = field(default_factory=list)  # exact paths a standard defines for it ("Entity.path")
    role: str | None = None                             # another role (None = the record's subject)


@dataclass
class Evidence:
    weights: dict[str, float]
    reasons: dict[str, str]
    kinds: dict[str, str]                 # standard | name | context | values
    role: str = SUBJECT

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


def evidence(f: Field, values, pack) -> Evidence:
    weights: dict[str, float] = {}
    reasons: dict[str, str] = {}
    kinds: dict[str, str] = {}

    def add(concept: str, w: float, why: str, kind: str):
        if w > weights.get(concept, 0):
            weights[concept], reasons[concept], kinds[concept] = w, why, kind

    plain = f.entity + "." + re.sub(r"\[[^\]]*\]", "", f.path)
    for key, c in pack.concepts.items():
        if f.path in c.positions or plain in c.positions:
            add(key, 1.0, f"posición estándar ({f.path if f.path in c.positions else plain})", "standard")

    desc = f.description or ""
    tail = desc.rsplit(":", 1)[-1] if ":" in desc else desc
    primary = words(f.label, f.path, tail)
    secondary = words(desc)
    for key, c in pack.concepts.items():
        hit = next((h for h in c.hints if f" {h} " in primary), None)
        if hit:
            add(key, 1.0, f"el nombre contiene «{hit}»", "name")
            continue
        hit = next((h for h in c.hints if f" {h} " in secondary), None)
        if hit:
            add(key, 0.5, f"la descripción menciona «{hit}»", "context")

    for key, (w, why) in pack.from_values(f, _flat(values)).items():
        add(key, w, why, "values")

    # "identifier.system" / "telecom.use" describe their neighbour .value; they aren't the data
    if is_metadata(f.path):
        weights = {k: round(w * 0.3, 3) for k, w in weights.items()}

    role = pack.subject
    everything = words(f.label, f.path, desc)
    for prefix, r in pack.role_positions.items():
        if f.path == prefix or f.path.startswith(prefix + ".") or f.entity == prefix:
            role = r
    for r, hints in pack.roles.items():
        if any(f" {h} " in everything for h in hints):
            role = r
    return Evidence(weights, reasons, kinds, role)


def concept_for_name(path: str, pack) -> str | None:
    """Meaning of a target field from its name. The leaf decides ("direccion.ciudad" is a city, not a street)."""
    for text in (words(path.rsplit(".", 1)[-1]), words(path.rsplit(".", 1)[-1], path)):
        for key, c in pack.concepts.items():
            if any(f" {h} " in text for h in c.hints):
                return key
    return None


def concept_for_text(text: str, pack) -> str | None:
    """Meaning from free text (a description, a CSV header): the first concept whose synonym appears."""
    w = words(text)
    for key, c in pack.concepts.items():
        if any(f" {h} " in w for h in c.hints):
            return key
    return None
