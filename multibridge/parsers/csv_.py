"""CSV / TSV: sniff encoding and delimiter, then reuse the spreadsheet table finder."""

from __future__ import annotations

import csv
import io
from collections import Counter
from pathlib import Path

from ..model import Dataset
from .table import add_tables
from .text import decode

DELIMITERS = [";", ",", "\t", "|"]


def sniff_delimiter(text: str) -> str:
    """Pick the delimiter that splits most lines into the same number of columns.

    csv.Sniffer gets confused by decimal commas ("62,4") in semicolon files,
    which is exactly what Spanish Excel exports look like.
    """
    lines = [l for l in text.splitlines()[:50] if l.strip()]
    best, best_score = ",", -1
    for d in DELIMITERS:
        counts = [len(next(csv.reader([l], delimiter=d))) - 1 for l in lines]
        counts = [c for c in counts if c > 0]
        if not counts:
            continue
        cols, freq = Counter(counts).most_common(1)[0]
        score = freq * 1000 + cols
        if score > best_score:
            best, best_score = d, score
    return best


def parse(data: bytes, name: str) -> Dataset:
    text, encoding = decode(data)
    delimiter = sniff_delimiter(text)
    ds = Dataset(source=name, format="csv")
    if encoding != "utf-8":
        ds.notes.append(f"Codificación detectada: {encoding} (no UTF-8).")
    shown = {"\t": "tabulador"}.get(delimiter, delimiter)
    ds.notes.append(f"Separador detectado: '{shown}'.")
    grid = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    add_tables(ds, Path(name).stem, grid)
    return ds
