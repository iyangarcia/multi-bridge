"""Command line.

    multibridge inspect FILE
    multibridge inspect FILE --as-ai                  # only what would be sent to the AI
    multibridge terms "TEXT" ...                      # the destination pack's terminology on free text

    multibridge expected                              # what the destination wants (from its example)
    multibridge map FILE                              # local Qwen proposes a recipe (or reuse an approved one)
    multibridge map FILE --model rules                # offline rules instead of the model
    multibridge approve recipes/drafts/NAME.json --by "Nombre"
    multibridge map FILE                              # same structure: applied without proposing again

The destination is the only `expected/*.example.json`, or the one given with --expected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import formats, packs, recipe as recipes
from .engine import run
from .expected import Expected, default_destination
from .ai.ollama import OllamaUnavailable
from .parsers import load
from .proposer import propose
from .profile import as_ai
from .records import to_rows

def _label(fmt: str) -> str:
    try:
        return formats.get(fmt).label
    except formats.UnsupportedFormat:
        return fmt


def _destination(args) -> Expected:
    return Expected.load(args.expected or default_destination())


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

    print(f"{ds.source}  ·  {_label(ds.format)}  ·  {len(ds.tables)} entidad(es)")
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
    pack = packs.get(args.pack or _destination(args).pack)
    normalizer = pack.normalizer(args.normalizer)
    if normalizer is None:
        print(f"el pack {pack.name!r} no tiene terminología", file=sys.stderr)
        return 1
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


def describe(t: dict) -> str:
    k = t["op"]
    if k == "date":
        return f"fecha {t['from']}→ISO"
    if k == "translate":
        return "traducir " + ", ".join(f"{a}→{b}" for a, b in list(t["values"].items())[:3])
    if k == "number":
        return "número" + (" (coma decimal)" if t.get("decimal") == "," else "")
    if k == "phone":
        return f"teléfono +{t['country']}"
    if k == "pad":
        return f"rellenar a {t['width']} cifras"
    if k == "scale":
        return f"×{t['factor']}"
    if k == "split":
        return f"separar, parte {t.get('index', 0)}"
    return {"join_columns": "unir columnas", "join_values": "unir varios valores", "first": "primer valor",
            "title": "Mayúscula Inicial"}.get(k, k)


def _light(confidence) -> str:
    if confidence is None:
        return "  "
    return "🟢" if confidence >= 0.85 else "🟡" if confidence >= 0.7 else "🔴"


def print_recipe(r: dict) -> None:
    src = r["source"]
    print(f"Propuesta para {src['file']} ({_label(src['format'])}) → {r['expected']}")
    print(f"Confianza: {r['confidence_kind']}\n")
    marks = {"mapped": "✓", "no_data": "–", "pending": "!"}
    for target, f in r["fields"].items():
        conf = f"{f['confidence']:.2f}" if f["confidence"] is not None else "    "
        cols = " + ".join(f["from"]) or "(sin dato)"
        ops = ", ".join(describe(t) for t in f["transforms"])
        print(f" {marks[f['status']]} {target:34} {_light(f['confidence'])} {conf}  {_short(cols, 28):28} {ops}")
        for issue in f.get("issues", []):
            print(f"   {'':34}          ↳ {issue}")
        if f["status"] != "mapped" and f.get("candidates"):
            cands = ", ".join(f"{c['column']} ({c['confidence']:.2f})" for c in f["candidates"])
            print(f"   {'':34}          candidatos: {cands}")
    if r["unmatched"]:
        print(f"\nColumnas de origen sin usar ({len(r['unmatched'])}): {_short(', '.join(r['unmatched']), 200)}")


def _write_output(result, file: str, out_dir: str, expected: Expected) -> Path:
    """The output in the destination's own format, checked by its plug-in, plus the run report."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(file).stem
    fmt = formats.get(expected.format)
    data = result.write(expected)
    target = out / f"{stem}{fmt.extension}"
    target.write_bytes(data)
    problems = fmt.check(data)
    if problems:
        result.report["output_problems"] = problems
        print(f"La salida no supera la comprobación de {fmt.label}:", file=sys.stderr)
        for pr in problems[:10]:
            print(f"  {pr}", file=sys.stderr)
    (out / f"{stem}.report.json").write_text(json.dumps(result.report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    return target


def _print_run(result, path: Path) -> int:
    r = result.report
    print(f"{r['accepted']}/{r['rows']} registros válidos → {path}")
    if r["rejected"]:
        print(f"{r['rejected']} registros apartados por no cumplir el destino:")
        for e in r["errors"][:10]:
            print(f"  fila {e['row']}: {e['field']} — {e['reason']}")
    if r["empty_fields"]:
        print("Campos sin dato: " + ", ".join(f"{k} ({v})" for k, v in r["empty_fields"].items()))
    return 0 if not r["rejected"] else 2


def cmd_expected(args) -> int:
    e = _destination(args)
    print(f"{e.id}  ({len(e.targets)} campos)")
    for t in e.targets:
        extra = [x for x in ("obligatorio" if t.required else "",
                             f"valores: {', '.join(t.enum)}" if t.enum else "",
                             f"unidad {t.unit}" if t.unit else "",
                             f"varios: {t.multiple}" if t.multiple else "") if x]
        print(f"  {t.path:34} {t.type:8} {str(t.concept or '?'):18} {'; '.join(extra)}")
    return 0


def cmd_map(args) -> int:
    expected = _destination(args)
    rows = to_rows(load(args.file))
    found = recipes.find(args.recipes, rows, expected)
    if found:
        path, r = found[0]
        a = r["approval"]
        print(f"Ya conozco este formato: receta '{r['recipe']}' ({path}), aprobada por {a['by']} el {a['at']}.")
        print("Se aplica sin volver a proponer. El motor valida cada registro.\n")
        result = run(rows, r, expected)
        return _print_run(result, _write_output(result, args.file, args.out, expected))
    if args.model != "rules":
        print(f"Pidiendo propuesta al modelo local ({args.model})…")
    try:
        draft = propose(rows, expected, model=args.model, name=Path(args.file).stem, recipes_dir=args.recipes)
    except OllamaUnavailable as e:
        print(f"No se pudo usar el modelo {args.model}: {e}")
        print("Arranca Ollama o usa --model rules.")
        return 1
    info = draft.get("proposer", {})
    if info.get("fallback_reason"):
        print(f"Modelo local no disponible ({info['fallback_reason']}): propuesta por reglas.\n")
    elif info.get("seconds") is not None:
        again = f", segunda pasada con razonamiento para {len(info['second_pass'])} campo(s)" if info["second_pass"] else ""
        print(f"Propuesta de {info['model']} en {info['seconds']} s{again}.\n")
    print_recipe(draft)
    path = recipes.save(draft, Path(args.recipes) / "drafts" / f"{draft['recipe']}.json")
    print(f"\nBorrador guardado en {path}. Revísalo (puedes editar el JSON) y apruébalo:")
    print(f'  multibridge approve "{path}" --by "Tu nombre"')
    blockers = recipes.problems(draft, expected)
    if blockers:
        print("\nAntes de aprobar hay que resolver:")
        for b in blockers:
            print(f"  ! {b}")
    return 0


def cmd_approve(args) -> int:
    expected = _destination(args)
    draft_path = Path(args.draft)
    try:
        approved = recipes.approve(recipes.load(draft_path), expected, args.by, carry=args.carry)
    except recipes.ApprovalError as e:
        print("No se puede aprobar:")
        for p in e.problems:
            print(f"  ! {p}")
        return 1
    folder = Path(args.recipes) if args.recipes else draft_path.parent.parent
    path = recipes.save(approved, folder / f"{approved['recipe']}.json")
    if draft_path.resolve() != path.resolve():
        draft_path.unlink()
    changed = [t for t, f in approved["fields"].items() if f.get("changed_by")]
    print(f"Aprobada por {approved['approval']['by']} → {path}")
    if changed:
        print(f"Campos cambiados respecto a la propuesta: {', '.join(changed)}")
    extras = approved["extras"]
    if extras["carry"]:
        print(f"Se llevan como campo extra: {', '.join(extras['carry'])}")
    if extras["drop"]:
        print(f"Se descartan ({len(extras['drop'])}, anotado): {_short(', '.join(extras['drop']), 160)}")
    print(f"Huella: {approved['approval']['sha256'][:16]}… (si se edita, hay que volver a aprobarla)")
    return 0


def cmd_run(args) -> int:
    expected = _destination(args)
    rows = to_rows(load(args.file))
    r = recipes.load(args.recipe)
    why = recipes.compatible(r, rows, expected)
    if why:
        print("La receta no encaja con este archivo:")
        for w in why:
            print(f"  ! {w}")
        return 1
    try:
        result = run(rows, r, expected)
    except recipes.ApprovalError as e:
        print(f"No se ejecuta: {e}")
        return 1
    return _print_run(result, _write_output(result, args.file, args.out, expected))


def cmd_serve(args) -> int:
    from .api import serve
    serve(Path(args.root).resolve(), args.port)
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

    t = sub.add_parser("terms", help="normalize free text to codes with a domain pack's terminology")
    t.add_argument("text", nargs="+")
    t.add_argument("--pack", help="domain pack (default: the destination's)")
    t.add_argument("--expected", help="example of the destination output")
    t.add_argument("--normalizer", help="the pack's normalizer (default: its first)")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_terms)

    def with_expected(sp):
        sp.add_argument("--expected", help="example of the destination output (default: the only one in expected/)")
        return sp

    e = with_expected(sub.add_parser("expected", help="show the destination fields read from its example"))
    e.set_defaults(func=cmd_expected)

    m = with_expected(sub.add_parser("map", help="reuse an approved recipe, or propose a new one"))
    m.add_argument("file")
    m.add_argument("--recipes", default="recipes", help="folder of approved recipes (drafts go in drafts/)")
    m.add_argument("--out", default="out")
    m.add_argument("--model", default="auto",
                   help='"auto" (local qwen3:8b, rules if Ollama is off), "rules", or a local model like qwen3:30b')
    m.set_defaults(func=cmd_map)

    a = with_expected(sub.add_parser("approve", help="approve a draft recipe (a person signs it)"))
    a.add_argument("draft")
    a.add_argument("--by", required=True, help="who approves")
    a.add_argument("--carry", action="append", default=[], metavar="COLUMN",
                   help="an unused source column to carry through as an extra field (repeatable); the rest are dropped")
    a.add_argument("--recipes", help="where approved recipes go (default: parent of drafts/)")
    a.set_defaults(func=cmd_approve)

    r = with_expected(sub.add_parser("run", help="run a specific approved recipe"))
    r.add_argument("file")
    r.add_argument("--recipe", required=True)
    r.add_argument("--out", default="out")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("serve", help="start the review web app on http://127.0.0.1 (this machine only)")
    s.add_argument("--port", type=int, default=8766)
    s.add_argument("--root", default=".", help="project folder (with web/, expected/, examples/, recipes/)")
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
