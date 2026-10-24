"""The output model shared by the engine and the writers.

An output *item* is flat: {target path: value}. Two kinds of keys are special:

    "pedido.lineas[]"   a repeated group: a list of sub-items, each {target path: value}
    EXTRAS              custom source fields carried through: {column: value}

`nest(item, expected)` turns an item into a nested record, the JSON view of the output (and
what the web app previews). Writers start from items, so each format decides its own shape.
"""

from __future__ import annotations

import datetime as dt

EXTRAS = "_extras"


def _set(out: dict, parts, value) -> None:
    *parents, leaf = parts
    for p in parents:
        out = out.setdefault(p, {})
    out[leaf] = value


def nest(item: dict, expected) -> dict:
    parts = {t.path: t.parts for t in expected.targets}
    out: dict = {}
    for key, value in item.items():
        if key == EXTRAS:
            if value:
                out[EXTRAS] = value
        elif key.endswith("[]"):
            prefix = key + "."
            _set(out, key[:-2].split("."), [
                _nest_sub({k[len(prefix):]: v for k, v in sub.items()}) for sub in value])
        else:
            _set(out, parts.get(key, key.split(".")), value)
    return out


def _nest_sub(sub: dict) -> dict:
    out: dict = {}
    for k, v in sub.items():
        _set(out, k.split("."), v)
    return out


def render(t, value) -> str:
    """A value as text, written the way the destination's example writes it (dates, decimals)."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(render(t, v) for v in value)
    r = t.render or {}
    if t.type == "date" and r.get("date"):
        try:
            return dt.date.fromisoformat(str(value)).strftime(r["date"])
        except ValueError:
            return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and t.type == "integer":
        value = int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{value:.{r['decimals']}f}" if r.get("decimals") is not None else str(value)
        return text.replace(".", ",") if r.get("decimal") == "," else text
    return str(value)


def extra_names(items: list[dict]) -> list[str]:
    return list(dict.fromkeys(k for it in items for k in (it.get(EXTRAS) or {})))
