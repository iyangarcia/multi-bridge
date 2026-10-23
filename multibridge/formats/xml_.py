"""XML: one record per repeated child of the root (<pedidos><pedido>...</pedido>...</pedidos>).

Paths are relative to the record element: `cliente.nombre`, `@numero` for an attribute,
`lineas.linea.producto` for nested elements; repeated elements give a list in that column.
As a destination, paths start with the record's tag (`pedido.cliente.nombre`, `pedido.@numero`),
and an element the example repeats (or the overlay's "$repeat" names) is a repeated group:
`pedido.lineas.linea[].producto`. The writer copies the example element by element.

Documents with a DOCTYPE are refused: no entity tricks (billion laughs, external entities).
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from ..model import Dataset, Field
from ..output import EXTRAS, render
from ..parsers.text import decode
from . import Destination, Format


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(data: bytes, name: str) -> ET.Element:
    text, _ = decode(data)
    if "<!DOCTYPE" in text[:2000].upper() or "<!ENTITY" in text.upper():
        raise ValueError(f"{name}: XML con DOCTYPE/ENTITY rechazado por seguridad")
    try:
        root = ET.fromstring(text.lstrip("﻿").encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError(f"{name}: XML mal formado ({e})") from None
    for el in root.iter():
        el.tag = _local(el.tag)
        el.attrib = {_local(k): v for k, v in el.attrib.items()}
    return root


def _records(root: ET.Element) -> tuple[str, list[ET.Element], bool]:
    """(record tag, record elements, whether the root only wraps them)."""
    kids = list(root)
    if kids and len({k.tag for k in kids}) == 1 and (len(kids) > 1 or len(kids[0]) or kids[0].attrib):
        return kids[0].tag, kids, True
    return root.tag, [root], False


def _flatten(el: ET.Element, prefix: str, rec: dict) -> None:
    for k, v in el.attrib.items():
        _add(rec, f"{prefix}@{k}", v)
    kids = list(el)
    if not kids:
        if el.text and el.text.strip():
            _add(rec, prefix[:-1] if prefix else el.tag, el.text.strip())
        return
    for kid in kids:
        _flatten(kid, f"{prefix}{kid.tag}.", rec)


def _add(rec: dict, path: str, value: str) -> None:
    if path not in rec:
        rec[path] = value
    elif isinstance(rec[path], list):
        rec[path].append(value)
    else:
        rec[path] = [rec[path], value]


class Xml(Format):
    name, label, extensions, mime = "xml", "XML", (".xml",), "application/xml"

    def sniff(self, data, name):
        head = data[:64].lstrip(b"\xef\xbb\xbf \r\n\t")
        return super().sniff(data, name) or head[:1] == b"<"

    def read(self, data, name):
        root = _parse(data, name)
        tag, elements, _ = _records(root)
        ds = Dataset(source=name, format=self.name)
        rows = []
        for el in elements:
            rec: dict = {}
            _flatten(el, "", rec)
            rows.append(rec)
        ds.tables[tag] = rows
        for p in dict.fromkeys(p for r in rows for p in r):
            ds.fields.append(Field(entity=tag, path=p, label=p))
        return ds

    # -- destination ------------------------------------------------------------------------------
    def destination(self, data, name, pack, options):
        from ..expected import target_from_column
        from ..profile import profile_field

        root = _parse(data, name)
        tag, elements, wrapped = _records(root)
        record = elements[0]
        repeat = set(options.get("$repeat") or [])
        targets, groups = [], {}

        def leaf(path: str, text: str | None, group: str | None):
            f = Field(entity=tag, path=path, label=path)
            profile_field(f, [text.strip()] if text and text.strip() else [], packs=[])
            t = target_from_column(path, f)
            t.group = group
            targets.append(t)

        def walk(el: ET.Element, path: str, group: str | None):
            for k, v in el.attrib.items():
                leaf(f"{path}.@{k}", v, group)
            kids = list(el)
            if not kids:
                if el.text and el.text.strip() or not el.attrib:
                    leaf(path, el.text, group)
                return
            seen: dict[str, int] = {}
            for kid in kids:
                seen[kid.tag] = seen.get(kid.tag, 0) + 1
            for kid_tag, n in seen.items():
                sub = f"{path}.{kid_tag}"
                first = next(k for k in kids if k.tag == kid_tag)
                many = n > 1 or sub in repeat
                if many and not len(first) and not first.attrib:   # <telefono>..</telefono> twice: one list
                    leaf(sub, first.text, group)
                    targets[-1].multiple = "list"
                    groups[sub] = kid_tag
                elif many and group is None:
                    groups[sub + "[]"] = kid_tag
                    walk(first, sub + "[]", sub + "[]")
                else:
                    walk(first, sub, group)

        walk(record, tag, None)
        template = {"root": root.tag if wrapped else None, "root_attrib": dict(root.attrib) if wrapped else {},
                    "record": record, "groups": groups}
        return Destination(self.name, targets, template=template)

    def write(self, items, expected):
        tpl = expected.template
        by_path = {t.path: t for t in expected.targets}
        out = ET.Element(tpl["root"] or "registros", tpl["root_attrib"])
        for item in items:
            rec = copy.deepcopy(tpl["record"])
            _fill(rec, rec.tag, item, by_path, tpl["groups"])
            extras = item.get(EXTRAS) or {}
            if extras:
                box = ET.SubElement(rec, "extras")
                for k, v in extras.items():
                    if v not in (None, "", []):
                        ET.SubElement(box, "campo", {"nombre": k}).text = "; ".join(map(str, v)) \
                            if isinstance(v, list) else str(v)
            out.append(rec)
        ET.indent(out)
        return ET.tostring(out, encoding="utf-8", xml_declaration=True) + b"\n"

    def check(self, data):
        try:
            _parse(data, "salida")
        except ValueError as e:
            return [str(e)]
        return []


def _fill(el: ET.Element, path: str, values: dict, by_path: dict, groups: dict) -> bool:
    """Fill a copy of the example element. Returns True when nothing is left in it (to remove it)."""
    for k in list(el.attrib):
        p = f"{path}.@{k}"
        if p in by_path:
            v = values.get(p)
            if v is None:
                del el.attrib[k]
            else:
                el.set(k, render(by_path[p], v))
    kids = list(el)
    if not kids:
        if path in by_path:
            v = values.get(path)
            el.text = None if v is None else render(by_path[path], v)
        return not (el.text or el.attrib)
    done: set[str] = set()
    for kid in kids:
        if kid.tag in done:
            continue
        gp = f"{path}.{kid.tag}[]"
        lp = f"{path}.{kid.tag}"
        if lp in groups and lp in by_path:     # a repeated plain element: one copy per value
            done.add(kid.tag)
            same = [k for k in list(el) if k.tag == kid.tag]
            at = list(el).index(same[0])
            for k in same:
                el.remove(k)
            v = values.get(lp)
            for n, x in enumerate(v if isinstance(v, list) else [] if v is None else [v]):
                c = copy.deepcopy(kid)
                c.text = render(by_path[lp], x)
                el.insert(at + n, c)
            continue
        if gp in groups:
            done.add(kid.tag)
            same = [k for k in list(el) if k.tag == kid.tag]
            at = list(el).index(same[0])
            for k in same:
                el.remove(k)
            for n, sub in enumerate(values.get(gp) or []):
                c = copy.deepcopy(kid)
                if not _fill(c, gp, sub, by_path, groups):
                    el.insert(at + n, c)
            continue
        if _fill(kid, f"{path}.{kid.tag}", values, by_path, groups):
            el.remove(kid)
    return not (len(el) or el.attrib or (el.text and el.text.strip()))


XML = Xml()
