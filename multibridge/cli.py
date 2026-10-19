"""Command line.

    multibridge inspect examples/huca_oviedo_hl7v23.hl7
    multibridge inspect examples/hospital_c_messy.xlsx --as-ai
    multibridge terms "DM2 mal controlada" "sospecha de NAC" "IRA" "DiabA"

    multibridge map examples/huca_oviedo_hl7v23.hl7 --contract contracts/cdss_paciente.v1.json
    multibridge approve drivers/drafts/huca_oviedo_hl7v23.json --contract contracts/cdss_paciente.v1.json --by "Nombre"
    multibridge map examples/huca_oviedo_hl7v23.hl7 --contract contracts/cdss_paciente.v1.json   # now reuses the driver
    multibridge contract-from-example examples/destino_expected.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import driver as drivers
from .contract import Contract, from_example
from .engine import run
from .matcher import propose
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


def describe_op(op: dict) -> str:
    k = op["op"]
    if k == "date":
        return f"fecha {op['from']}→ISO"
    if k == "map":
        return "traducir " + ", ".join(f"{a}→{b}" for a, b in list(op["values"].items())[:3])
    if k == "number":
        return "número" + (" (coma decimal)" if op.get("decimal") == "," else "")
    if k == "phone":
        return f"teléfono +{op['country']}"
    if k == "pad":
        return f"rellenar a {op['width']} cifras"
    if k == "concat":
        return "unir campos"
    if k == "join":
        return "unir varios valores"
    if k == "first":
        return "primer valor"
    if k == "title":
        return "Mayúscula Inicial"
    if k == "scale":
        return f"×{op['factor']}"
    return k


def print_plan(d: dict) -> None:
    src = d["source"]
    join = f", enlazado por {src['join']}" if src["join"] else ""
    print(f"Propuesta para {src['file']} ({FORMATS.get(src['format'], src['format'])}) → {d['contract']}")
    print(f"Entidad raíz: {src['root']}{join}.  Puntuación: {d['score_kind']}\n")
    marks = {"mapped": "✓", "no_source": "–", "pending": "!"}
    for m in d["mappings"]:
        sources = " + ".join(s["path"] for s in m["sources"]) or "(sin origen)"
        score = f"{m['score']:.2f}" if m["score"] is not None else "    "
        ops = ", ".join(describe_op(o) for o in m["ops"])
        print(f" {marks[m['status']]} {m['target']:34} {score}  {_short(sources, 30):30} {ops}")
        for issue in m["issues"]:
            print(f"   {'':34}       ↳ {issue}")
        if m["status"] != "mapped" and m.get("candidates"):
            cands = ", ".join(f"{c['path']} ({c['score']:.2f})" for c in m["candidates"])
            print(f"   {'':34}       candidatos: {cands}")
    extra = [u for u in d["unmatched_sources"] if u["looks_like"] or u["custom"]]
    if d["unmatched_sources"]:
        print(f"\nCampos de origen sin usar: {len(d['unmatched_sources'])}"
              + (f" (a revisar: {', '.join(u['path'] + (' ~' + u['looks_like'] if u['looks_like'] else '') for u in extra)})"
                 if extra else ""))


def _write_output(result, file: str, out_dir: str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(file).stem
    (out / f"{stem}.json").write_text(json.dumps(result.records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / f"{stem}.report.json").write_text(json.dumps(result.report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    return out / f"{stem}.json"


def _print_run(result, path: Path) -> None:
    r = result.report
    print(f"{r['accepted']}/{r['processed']} registros válidos → {path}")
    if r["rejected"]:
        print(f"{r['rejected']} registros separados por no cumplir el contrato:")
        for e in r["errors"][:10]:
            print(f"  registro {e['record']}: {e['target']} — {e['reason']}")
    if r["empty_fields"]:
        print("Campos vacíos: " + ", ".join(f"{k} ({v})" for k, v in r["empty_fields"].items()))


def cmd_map(args) -> int:
    contract = Contract.load(args.contract)
    ds = load(args.file)
    found = drivers.find_compatible(args.drivers, ds, contract)
    if found:
        path, drv = found[0]
        a = drv["approval"]
        print(f"Ya conozco este formato: driver '{drv['driver']}' ({path}), aprobado por {a['by']} el {a['at']}.")
        print("Se aplica sin volver a proponer el mapeo. El motor valida cada registro.\n")
        result = run(ds, drv, contract)
        _print_run(result, _write_output(result, args.file, args.out))
        return 0 if not result.rejected else 2
    plan = propose(ds, contract, name=Path(args.file).stem)
    print_plan(plan)
    draft = drivers.save(plan, Path(args.drivers) / "drafts" / f"{plan['driver']}.json")
    blockers = drivers.problems(plan, contract)
    print(f"\nBorrador guardado en {draft}. Revísalo (puedes editar el JSON) y apruébalo:")
    print(f'  multibridge approve "{draft}" --contract "{args.contract}" --by "Tu nombre"')
    if blockers:
        print("\nAntes de aprobar hay que resolver:")
        for b in blockers:
            print(f"  ! {b}")
    return 0


def cmd_approve(args) -> int:
    contract = Contract.load(args.contract)
    draft_path = Path(args.draft)
    try:
        approved = drivers.approve(drivers.load(draft_path), contract, args.by)
    except drivers.ApprovalError as e:
        print("No se puede aprobar:")
        for p in e.problems:
            print(f"  ! {p}")
        return 1
    target_dir = Path(args.drivers) if args.drivers else draft_path.parent.parent
    path = drivers.save(approved, target_dir / f"{approved['driver']}.json")
    if draft_path.resolve() != path.resolve():
        draft_path.unlink()
    print(f"Aprobado por {approved['approval']['by']} → {path}")
    print(f"Huella del plan: {approved['approval']['plan_sha256'][:16]}… (si se edita, hay que volver a aprobarlo)")
    return 0


def cmd_run(args) -> int:
    contract = Contract.load(args.contract)
    ds = load(args.file)
    drv = drivers.load(args.driver)
    why = drivers.compatible(drv, ds, contract)
    if why:
        print("El driver no es compatible con este archivo:")
        for w in why:
            print(f"  ! {w}")
        return 1
    try:
        result = run(ds, drv, contract)
    except drivers.ApprovalError as e:
        print(f"No se ejecuta: {e}")
        return 1
    _print_run(result, _write_output(result, args.file, args.out))
    return 0 if not result.rejected else 2


def cmd_contract(args) -> int:
    example = json.loads(Path(args.example).read_text(encoding="utf-8"))
    c = from_example(example, name=args.name)
    print(json.dumps(c.to_dict(), ensure_ascii=False, indent=2))
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

    m = sub.add_parser("map", help="reuse an approved driver, or propose a new mapping plan")
    m.add_argument("file")
    m.add_argument("--contract", required=True)
    m.add_argument("--drivers", default="drivers", help="folder with approved drivers (drafts go in drafts/)")
    m.add_argument("--out", default="out")
    m.set_defaults(func=cmd_map)

    a = sub.add_parser("approve", help="approve a draft driver (a person signs it)")
    a.add_argument("draft")
    a.add_argument("--contract", required=True)
    a.add_argument("--by", required=True, help="who approves")
    a.add_argument("--drivers", help="where approved drivers go (default: parent of drafts/)")
    a.set_defaults(func=cmd_approve)

    r = sub.add_parser("run", help="run a specific approved driver")
    r.add_argument("file")
    r.add_argument("--driver", required=True)
    r.add_argument("--contract", required=True)
    r.add_argument("--out", default="out")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("contract-from-example", help="draft an EXPECTED contract from an example output JSON")
    c.add_argument("example")
    c.add_argument("--name", default="contrato")
    c.set_defaults(func=cmd_contract)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
