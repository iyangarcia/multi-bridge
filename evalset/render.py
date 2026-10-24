"""Write a table of invented values as a messy file: CSV, Excel, JSON or XML.

A table is a list of columns (header, raw values per row). The domain decides the values and their
shapes; this module only decides how the file around them is written, and says which source
column name the reader will give each header (JSON nests "section.key"; XML needs tag names).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from openpyxl import Workbook


@dataclass
class Column:
    header: str
    values: list            # one raw value per row: str, int, float, datetime.date or None
    section: str = ""       # JSON may nest the column under this key


def _text(v, date_format: str) -> str:
    if v is None:
        return ""
    if isinstance(v, dt.date):
        return v.strftime(date_format)
    return str(v)


def csv_file(cols: list[Column], r, title: str) -> tuple[bytes, dict, dict[str, str]]:
    sep = r.choice([";", ";", ",", "\t"])
    encoding = r.choice(["utf-8", "utf-8-sig", "cp1252"])
    lines = []
    if r.random() < 0.35:
        lines += [[title], []]
    lines.append([c.header for c in cols])
    for i in range(len(cols[0].values)):
        lines.append([_text(c.values[i], "%d/%m/%Y") for c in cols])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator=r.choice(["\r\n", "\n"]))
    for line in lines:
        w.writerow(line)
    if r.random() < 0.3:
        buf.write("\r\n")
    data = buf.getvalue().encode(encoding, errors="replace")
    return data, {"separator": {"\t": "tab"}.get(sep, sep), "encoding": encoding, "title_line": len(lines) > len(cols[0].values) + 1}, \
        {c.header: c.header for c in cols}


def xlsx_file(cols: list[Column], r, title: str) -> tuple[bytes, dict, dict[str, str]]:
    wb = Workbook()
    ws = wb.active
    second = r.random() < 0.3
    if second:      # the data on the second sheet, a cover sheet first
        ws.title = "Portada"
        ws.append([title])
        ws = wb.create_sheet("Datos")
    else:
        ws.title = "Datos"
    titled = r.random() < 0.4
    if titled:
        ws.append([title])
        ws.append([])
    ws.append([c.header for c in cols])
    for i in range(len(cols[0].values)):
        ws.append([c.values[i] for c in cols])
    if r.random() < 0.3:
        ws.append([])
        ws.append([f"Total: {len(cols[0].values)}"])
    wb.properties.created = wb.properties.modified = dt.datetime(2026, 1, 1)
    buf = io.BytesIO()
    wb.save(buf)
    return _fixed_zip(buf.getvalue()), {"second_sheet": second, "title_line": titled}, {c.header: c.header for c in cols}


def _fixed_zip(data: bytes) -> bytes:
    """The same workbook bytes for the same seed: every zip entry gets a fixed timestamp."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(zipfile.ZipInfo(info.filename, date_time=(2026, 1, 1, 0, 0, 0)), src.read(info.filename),
                         compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()


def json_file(cols: list[Column], r, title: str) -> tuple[bytes, dict, dict[str, str]]:
    nested = r.random() < 0.4 and any(c.section for c in cols)
    names = {c.header: f"{c.section}.{c.header}" if nested and c.section else c.header for c in cols}
    out = []
    for i in range(len(cols[0].values)):
        rec: dict = {}
        for c in cols:
            v = c.values[i]
            v = v.isoformat() if isinstance(v, dt.date) else v
            if nested and c.section:
                rec.setdefault(c.section, {})[c.header] = v
            else:
                rec[c.header] = v
        out.append(rec)
    text = json.dumps(out, ensure_ascii=r.random() < 0.3, indent=r.choice([None, 2]))
    return text.encode("utf-8"), {"nested": nested}, names


def tag(header: str) -> str:
    """An XML element name for a header: "F. Nac." -> "f_nac"."""
    s = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "campo"
    return "c_" + s if s[0].isdigit() else s


def xml_file(cols: list[Column], r, title: str, root: str, item: str) -> tuple[bytes, dict, dict[str, str]]:
    names, seen = {}, set()
    for c in cols:
        t = tag(c.header)
        while t in seen:
            t += "_2"
        seen.add(t)
        names[c.header] = t
    attr = cols[0].header if r.random() < 0.4 else None     # the first column (the key) as an attribute
    if attr:
        names[attr] = "@" + names[attr]
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f"<{root}>"]
    for i in range(len(cols[0].values)):
        key = cols[0].values[i]
        head = f' {names[attr][1:]}="{_esc(_text(key, "%Y-%m-%d"))}"' if attr and key is not None else ""
        out.append(f"  <{item}{head}>")
        for c in cols:
            if c.header == attr:
                continue
            v = c.values[i]
            if v is not None:
                out.append(f"    <{names[c.header]}>{_esc(_text(v, '%Y-%m-%d'))}</{names[c.header]}>")
        out.append(f"  </{item}>")
    out.append(f"</{root}>")
    return ("\n".join(out) + "\n").encode("utf-8"), {"key_as_attribute": bool(attr)}, names


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
