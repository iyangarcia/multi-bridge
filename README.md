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
| **Same word, different person** | HL7 `PV1-7.2` is the *doctor's* surname, `PID-5.1` the patient's | role-aware matching: never maps the doctor onto the patient |
| **Undocumented fields** | a `ZPA` segment holding `A+`, `58.5`, `164` with no documentation | recognises blood group / weight / height from the values, and flags it "deducido solo por los valores: revisar" |
| **Conventions** | `M` = *mujer* (H/M) or *male* (M/F); `0+` vs `O+`; `62,4`; `600777888` | translates by convention, leaves a lone `M` for a human, validates against the contract |

## Architecture

```
 HL7 v2 ─┐                                          ┌─ terms/  Normalizer interface
 FHIR   ─┤   parsers/  ──►  Dataset + Field[]  ──►  │   ├─ lexical (offline, today)
 CSV    ─┤   (one shape                profile.py   │   └─ JEV / LLM / SNOMED server (next)
 Excel  ─┘    for all)     types, units, sensitive  │
                                     │              └─ as_ai(): structure + profile only,
                                     ▼                  never the values of sensitive fields
   contracts/ (EXPECTED) ──►  matcher.py  ──►  draft driver  ──►  human approves (plan hash)
                              rules today;          │                       │
                              local Qwen / JEV      ▼                       ▼
                              next (docs/JEV.md)   drivers/*.json ──►  engine.py ──► validated records
                                                   reused when the same layout comes back (no AI)
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

### Map a hospital file onto EXPECTED

```bash
multibridge map examples/huca_oviedo_hl7v23.hl7 --contract contracts/cdss_paciente.v1.json
multibridge approve drivers/drafts/huca_oviedo_hl7v23.json --contract contracts/cdss_paciente.v1.json --by "Your name"
multibridge map examples/huca_oviedo_hl7v23.hl7 --contract contracts/cdss_paciente.v1.json   # reuses the driver
```

```
 ✓ paciente.nombre                    0.94  PID-5.2                        Mayúscula Inicial
 ✓ paciente.fecha_nacimiento          0.94  PID-7                          fecha %Y%m%d→ISO
 ✓ paciente.sexo                      0.94  PID-8                          traducir F→female, M→male
 ✓ datos_clinicos.grupo_sanguineo     0.86  ZPA-2                          traducir 0+→O+, 0-→O-, primer valor
                                            ↳ deducido solo por los valores: revisar
                                            ↳ campo personalizado del centro (no estándar)
 ✓ datos_clinicos.medico_responsable  0.82  PV1-7.3 + PV1-7.2              unir campos, Mayúscula Inicial, primer valor
```

The same contract and the same code map the CSV (Hospital C), the FHIR API (Hospital B) and the
HL7 v2.3 feed (Hospital A). `tests/test_golden.py` checks the plan and every output record for all
three. `multibridge contract-from-example examples/destino_expected.json` drafts a contract from one
example output.

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
| `multibridge/contract.py` | EXPECTED contract: types, concepts, enums, patterns, ranges, missing-data policy; `from_example()` |
| `multibridge/concepts.py` | domain knowledge: synonyms, standard HL7/FHIR positions, value patterns, roles, value translations |
| `multibridge/matcher.py` | rules matcher → draft driver (mappings, ops, issues, unmatched fields) |
| `multibridge/driver.py` | draft → approved lifecycle, plan hash, reuse by structural signature |
| `multibridge/engine.py` | deterministic engine: declarative ops, joins (HL7 message, FHIR reference), validation, run report |
| `contracts/` | `cdss_paciente.v1.json`: what the clinical app expects |
| `examples/` | synthetic data for the 3 hospitals plus messy variants (`build_examples.py` regenerates them) |
| `tests/` | parsers, terminology, privacy, matcher, engine, and the 3-hospital golden test (`tests/golden/`) |

## Plugging in JEV (or any other normalizer)

Implement `normalize(text) -> list[ConceptMatch]` from `multibridge/terms/base.py` and register it
in `multibridge/terms/__init__.py`. The profiler, CLI and tests use whatever normalizer is
registered, so nothing else changes.

## Honest limits

- `terms/seed_es.py` is a **demo seed** of about 30 ICD-10 categories. Before real use, load the
  official CIE-10-ES release and/or SNOMED CT (free in Spain as a SNOMED member country).
- Fuzzy `similarity` is a string similarity, **not a calibrated probability**. Calibration
  needs a labelled evaluation set (see the design doc).
- The matcher's `score` is a rules similarity, **not a calibrated probability** either.
- Not supported yet: key-value rows (HL7 `OBX-5` / FHIR `Observation.value`, where the code says
  whether a row is weight or height). The matcher marks them *pending* instead of guessing.
  Splitting a combined "Nombre y apellidos" column is not supported either.
- Review means editing the draft JSON for now. There is no review UI yet.
- All data in `examples/` is synthetic.

## Roadmap

1. ~~Matcher, declarative driver + engine, 3-hospital golden test~~ (done)
2. Decider interface copying Jev's choice/score/noul, with `rules` / `local` (Ollama + Qwen) / `jev` backends
3. Code-filtered sources (OBX / Observation) and a terminology op (diagnosis text → ICD-10 via `terms/`)
4. Synthetic evaluation set generator (Synthea → messy files + ground truth) to compare rules, Qwen 8B and 30B, and calibrate scores
5. FastAPI service + the existing web UI for review, one Docker image for on-prem or private cloud
