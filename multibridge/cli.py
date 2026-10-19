"""Command line.

    multibridge inspect examples/huca_oviedo_hl7v23.hl7
    multibridge inspect examples/hospital_c_messy.xlsx --as-ai
    multibridge terms "DM2 mal controlada" "sospecha de NAC" "IRA" "DiabA"
"""

from __future__ import annotations

import argparse
import json
import sys

from .parsers import load
from .profile import as_ai
from .terms import get_normalizer

FORMATS = {"csv": "CSV", "excel": "Excel", "fhir": "HL7 FHIR", "json": "JSON", "hl7v2": "HL7 v2"}


def _short(s: str, n: int) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_inspect(args) -> int:
    ds = load(args.file)
    if args.as_ai:
        print(json.dumps(as_ai(ds, args.level), ensure_ascii=False, indent=2))
        return 0
    if args.json:
        print(json.dumps({"source": ds.source, "format": ds.format, "notes": ds.notes,
                          "fields": [f.to_dict() for f in ds.fields]}, ensure_ascii=False, indent=2))
        return 0

    print(f"{ds.source}  ·  {FORMATS.get(ds.format, ds.format)}  ·  {len(ds.tables)} entidad(es)")
    for note in ds.notes:
        print(f"  ! {note}")
    for entity, rows in ds.tables.items():
        print(f"\n{entity}  ({len(rows)} registros)")
        for f in (x for x in ds.fields if x.entity == entity):
            flags = []
            if f.sensitive:
                flags.append(f"SENSIBLE: {f.sensitive_reason}")
            if f.custom:
                flags.append("CUSTOM")
            if f.unit:
                flags.append(f.unit)
            if f.null_ratio:
                flags.append(f"{int(f.null_ratio * 100)}% vacío")
            typ = f.dtype + (f" ({f.format})" if f.format else "")
            print(f"  {_short(f.path, 34):34} {_short(typ, 24):24} {f.kind:16} {', '.join(flags)}")
            if f.description:
                print(f"  {'':34} {_short(f.description, 90)}")
            if f.categories:
                print(f"  {'':34} valores: {', '.join(f.categories)}")
            if f.concepts:
                c = f.concepts
                line = f"terminología: {c['recognised']}/{c['values']} reconocidos ({', '.join(c['systems'])})"
                print(f"  {'':34} {line}")
                if c["ambiguous"]:
                    print(f"  {'':34} ambiguos → revisar: {', '.join(c['ambiguous'])}")
                if c["unknown"]:
                    print(f"  {'':34} desconocidos → preguntar al centro: {', '.join(c['unknown'])}")
    return 0


def cmd_terms(args) -> int:
    normalizer = get_normalizer(args.normalizer)
    out = []
    for text in args.text:
        matches = normalizer.normalize(text)
        if args.json:
            out.append({"input": text, "matches": [m.to_dict() for m in matches]})
            continue
        print(f"\n{text}")
        for m in matches:
            qual = "" if m.qualifier == "confirmed" else f"  [{m.qualifier}]"
            if m.status == "matched":
                extra = f" ~{m.similarity}" if m.similarity else ""
                print(f"  → {m.code} {m.display}  ({m.method}{extra}){qual}")
            elif m.status == "ambiguous":
                alts = " | ".join(f"{c or '—'} {d}" for c, d in m.alternatives)
                print(f"  ? ambiguo: {alts}{qual}")
            else:
                print(f"  ✗ desconocido{qual}")
            if m.modifiers:
                print(f"    modificadores: {', '.join(m.modifiers)}")
            if m.note:
                print(f"    {m.note}")
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="multibridge", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("inspect", help="parse a file and show its fields")
    i.add_argument("file")
    i.add_argument("--as-ai", action="store_true", help="show only what would be sent to the AI")
    i.add_argument("--level", default="profile", choices=["structure", "profile"])
    i.add_argument("--json", action="store_true")
    i.set_defaults(func=cmd_inspect)

    t = sub.add_parser("terms", help="normalize clinical text to codes")
    t.add_argument("text", nargs="+")
    t.add_argument("--normalizer", default="lexical")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_terms)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
