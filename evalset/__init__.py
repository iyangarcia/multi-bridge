"""Phase 9 evaluation set: invented records rendered as messy files whose correct answer is known.

    from evalset import generate, cases
    case = generate("pacientes", "csv", seed=7)
    case.data, case.name     the file (bytes) and its name
    case.destination         the destination example it is meant for
    case.truth               target -> the source columns that hold it ([] = the file doesn't have it)
    case.values              per source row: target -> the correct output value (None = no value)
    case.style               how this file was made messy (for the report)

Two domains, so the clinical pack and the no-pack path are both measured:
    pacientes  -> expected/cdss_paciente.example.json      (clinical pack)
                  CSV, Excel, JSON, XML, HL7 v2, FHIR
    pedidos    -> examples/destinos/pedido_json.example.json (no pack, lines grouped by order)
                  CSV, Excel, JSON, XML

A seed gives the same file every time. The messiness is drawn from what real exports do:
names in Spanish, English or cryptic codes, a section prefix, a title line, odd encodings and
separators, several date shapes, sex codes, units (g/kg, m/cm), decimal commas, capitals,
split or combined name columns, postal codes that lost their zero, missing fields, and
distractor columns (another person's phone, an admission date, a room number...).

Every name, number and address is invented (docs/COMPLIANCE.md C1). evalset/grade.py grades a
proposal against the truth; scripts/calibrate.py measures and calibrates the confidences.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Case:
    domain: str
    format: str
    seed: int
    name: str
    data: bytes
    destination: Path
    truth: dict[str, list[str]]
    values: list[dict]
    style: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.domain}/{self.format}/{self.seed}"


def _domains():
    from . import orders, patients
    return {"pacientes": patients, "pedidos": orders}


def formats(domain: str) -> tuple[str, ...]:
    return _domains()[domain].FORMATS


DOMAINS = ("pacientes", "pedidos")


def generate(domain: str, fmt: str, seed: int) -> Case:
    module = _domains()[domain]
    if fmt not in module.FORMATS:
        raise ValueError(f"{domain}: no hay generador para {fmt}")
    r = random.Random(f"{domain}/{fmt}/{seed}")
    return module.generate(r, fmt, seed)


def cases(n: int, start: int = 0) -> list[Case]:
    """n cases spread evenly over every (domain, format) pair, seeds start, start+1, ..."""
    pairs = [(d, f) for d in DOMAINS for f in formats(d)]
    return [generate(*pairs[i % len(pairs)], seed=start + i // len(pairs)) for i in range(n)]
