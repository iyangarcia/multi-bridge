# Multi Bridge — universal healthcare data mapper

> Show it one example of how you want your data. It maps the rest, a human approves, and a
> deterministic engine does the transformation.

Started at **Hackathon TalentUO 2026** (Reto 5, Pragmatech AI Solutions, Grupo 5). The challenge is
to connect one clinical application to three hospitals that speak HL7 v2.3, HL7 FHIR and Excel,
**without writing one integration per hospital**.

## Why this is harder than renaming columns

Mapping `F. Nacimiento` → `birthDate` is the easy part. Real hospital data breaks in three ways:

| Problem | Example | What this repo does |
|---|---|---|
| **Clinical values** | `DM2 mal controlada`, `Diabetes tipo II`, `E11.9`, `diabetis tipo 2` | normalizes all four to ICD-10 **E11** and keeps the modifier |
| **Clinical meaning** | `sospecha de NAC`, `AP de IAM`, `no HTA` | separates *suspected*, *history* and *negated* from *confirmed* |
| **Ambiguity** | `IRA` = renal **or** respiratory failure; `FA` = atrial fibrillation **or** alkaline phosphatase | never guesses: marks it *ambiguous* with both options for a human |
| **Unknown local jargon** | `DiabA` | marks it *unknown* and asks the hospital what it means |
| **Custom fields** | HL7 `ZPA`/`ZTR` segments, FHIR extensions, unnamed Excel columns | flags them `custom` and keeps their documentation |
| **Human-made Excel** | title rows, merged group headers, footers, 2 tables per sheet, comments, formulas | finds the real table, builds `Antropometría / Peso (kg)` labels, reads comments as field docs |

## Architecture

```
 HL7 v2 ─┐                                          ┌─ terms/  Normalizer interface
 FHIR   ─┤   parsers/  ──►  Dataset + Field[]  ──►  │   ├─ lexical (offline, today)
 CSV    ─┤   (one shape                profile.py   │   └─ JEV / LLM / SNOMED server (next)
 Excel  ─┘    for all)     types, units, sensitive  │
                                     │              └─ as_ai(): structure + profile only,
                                     ▼                  never the values of sensitive fields
                     next: matcher → human review → declarative driver → engine
```

Every format becomes the **same** `Field` list (path, description, type, format, unit, kind,
sensitive, categories, terminology summary). Nothing downstream knows whether the data came from
HL7 or Excel. That is the "no integration per hospital" claim, expressed in code.

## Try it

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # macOS/Linux: .venv/bin/pip
multibridge inspect examples/hospital_c_messy.xlsx
multibridge inspect examples/huca_oviedo_hl7v23.hl7 --as-ai
multibridge terms "DM2 mal controlada" "sospecha de NAC" "AP de IAM; HTA" "IRA" "DiabA"
pytest
```

```
DM2 mal controlada
  → E11 Diabetes mellitus tipo 2  (abbreviation)
    modificadores: mal controlada
Sospecha de NAC
  → J18 Neumonía, organismo no especificado  (abbreviation)  [suspected]
IRA
  ? ambiguo: N17 Insuficiencia renal aguda | J96.0 Insuficiencia respiratoria aguda
DiabA
  ✗ desconocido
    Posible abreviatura local desconocida: pedir aclaración al centro
```

## Layout

| Path | What |
|---|---|
| `multibridge/model.py` | `Dataset` and `Field`: the shared shape |
| `multibridge/parsers/` | `csv_`, `excel`, `fhir` (+ NDJSON, plain JSON), `hl7v2` (no dependency), `table` (finds tables in messy grids) |
| `multibridge/profile.py` | type/format/unit inference, sensitive-data detection, `as_ai()` privacy view |
| `multibridge/terms/` | `Normalizer` interface, rule-based `LexicalNormalizer`, small Spanish ICD-10 seed |
| `examples/` | synthetic data for the 3 hospitals plus messy variants (`build_examples.py` regenerates them) |
| `tests/` | parsers, terminology, and a privacy test that fails if any sensitive value reaches the AI view |

## Plugging in JEV (or any other normalizer)

Implement `normalize(text) -> list[ConceptMatch]` from `multibridge/terms/base.py` and register it
in `multibridge/terms/__init__.py`. The profiler, CLI and tests use whatever normalizer is
registered, so nothing else changes.

## Honest limits

- `terms/seed_es.py` is a **demo seed** of about 30 ICD-10 categories. Before real use, load the
  official CIE-10-ES release and/or SNOMED CT (free in Spain as a SNOMED member country).
- Fuzzy `similarity` is a string similarity, **not a calibrated probability**. Calibration
  needs a labelled evaluation set (see the design doc).
- Not built yet: the matcher, the review UI, the driver engine, Docker.
- All data in `examples/` is synthetic.

## Roadmap

1. Matcher: propose source → EXPECTED field pairs (port of the hackathon `matcher.js`, then an LLM)
2. Declarative driver + deterministic engine (copy, rename, date, value map, concat/split, terminology map)
3. Golden tests: the 3 hospitals → identical `destino_expected.json`
4. Synthetic training/evaluation set generator (Synthea → messy files + ground truth)
5. FastAPI service + the existing web UI, one Docker image for on-prem or private cloud
