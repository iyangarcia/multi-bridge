"""Decoding helpers shared by the text-based parsers."""

from __future__ import annotations


def decode(data: bytes) -> tuple[str, str]:
    """Exports are UTF-8 or Windows-1252 in practice; try them in that order."""
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def column_letter(idx: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out
