"""How often proposals at each confidence were right on the generated evaluation set (ROADMAP phase 9).

calibration.json is written by scripts/calibrate.py: per proposer ("rules", "qwen3:8b"...), score
bands with the measured hit rate (made non-decreasing with the score), how many proposals it rests
on, and its 95% interval. The raw score still orders the review; this says what a score has meant
in tests. The rates come from synthetic files: whoever shows them must say so (docs/CALIBRATION.md).
A proposer that hasn't been measured gets None, never a made-up rate.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).with_name("calibration.json")


@lru_cache(maxsize=1)
def table() -> dict:
    try:
        return json.loads(TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def measured(confidence: float | None, proposer: str | None) -> dict | None:
    """{"rate", "n", "interval", "band"} for this confidence, or None if it was never measured."""
    if confidence is None or not proposer or proposer not in table():
        return None
    bands = table()[proposer]["bands"]
    for i, b in enumerate(bands):
        last = i == len(bands) - 1
        if b["low"] <= confidence < b["high"] or (last and confidence == b["high"]):
            if b["rate"] is None or not b["n"]:
                return None
            return {"rate": b["rate"], "n": b["n"], "interval": b["interval"], "band": [b["low"], b["high"]]}
    return None
