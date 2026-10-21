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
| **Conventions** | `M` = *mujer* (H/M) or *male* (M/F); `0+` vs `O+`; `62,4`; `600777888` | translates by convention, leaves a lone `M` for a human, validates against the destination rules |

## How it works (the hackathon flow)

> *"Enséñale un ejemplo de cómo quieres los datos y la IA hace el resto."*

```
 1. destination example          expected/cdss_paciente.example.json (+ optional .rules.json)
                                         │  target fields + types
 2. source file ─► parsers/ ─► records.py: one flat row per patient
    (HL7, FHIR,     any format    (HL7 segments side by side, FHIR resources attached)
     CSV, Excel)                         │
 3. local Qwen (Ollama) sees only the masked view ──►  draft recipe: per target, columns + transforms + 🟢🟡🔴
    (rules if Ollama is off)  the model picks columns, the code picks formats; the reply is checked
                                         │
 4. a human reviews and approves ──►  recipes/<name>.json  (who, when, hash, what was changed)
                                         │
 5. engine.py: row by row, fixed transforms, validated against the example + rules ──► records
    same structure next time? the recipe is reused, no AI involved
```

Every format becomes the same `Field` list and then the same flat rows. Nothing after
`records.py` knows whether the data came from HL7 or Excel: that is the "no integration per
hospital" claim, expressed in code.

## Try it

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # macOS/Linux: .venv/bin/pip
multibridge inspect examples/hospital_c_messy.xlsx
multibridge inspect examples/huca_oviedo_hl7v23.hl7 --as-ai
multibridge terms "DM2 mal controlada" "sospecha de NAC" "AP de IAM; HTA" "IRA" "DiabA"
pytest
```

### Map a hospital file onto the destination

```bash
multibridge expected                                   # fields read from expected/cdss_paciente.example.json
multibridge map examples/huca_oviedo_hl7v23.hl7        # local qwen3:8b proposes a draft recipe (~1 min)
multibridge map examples/huca_oviedo_hl7v23.hl7 --model qwen3:30b   # or the bigger model, or --model rules
multibridge approve recipes/drafts/huca_oviedo_hl7v23.json --by "Your name"
multibridge map examples/huca_oviedo_hl7v23.hl7        # same structure: reuses the recipe
```

```
 ✓ paciente.nombre                    🟢 0.94  PID-5.2                      Mayúscula Inicial
 ✓ paciente.fecha_nacimiento          🟢 0.94  PID-7                        fecha %Y%m%d→ISO
 ✓ paciente.sexo                      🟢 0.94  PID-8                        traducir F→female, M→male
 ✓ datos_clinicos.peso_kg             🔴 0.69  ZPA-3                        número
                                               ↳ deducido solo por los valores: revisar
                                               ↳ campo personalizado del centro (no estándar)
 ✓ datos_clinicos.medico_responsable  🟢 0.82  PV1-7.3 + PV1-7.2            unir columnas, Mayúscula Inicial
```

The same destination example and the same code map the CSV (Hospital C), the FHIR API
(Hospital B) and the HL7 v2.3 feed (Hospital A). `tests/test_golden.py` checks the proposal and
every output record for all three. The confidence numbers are hand-weighted rules, **not
probabilities**, until they are calibrated (roadmap phase 5).

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
| `multibridge/parsers/` | read: `hl7v2` (no dependency), `fhir` (+ NDJSON, plain JSON), `csv_`, `excel`, `table` (finds tables in messy grids) |
| `multibridge/model.py` | `Dataset` and `Field`: the shape every parser produces |
| `multibridge/profile.py` | per field: type, format, unit, sensitive data; `as_ai()` = what the AI may see |
| `multibridge/terms/` | diagnosis text → ICD-10 (qualifiers, abbreviations, ambiguity), `Normalizer` interface |
| `multibridge/records.py` | one flat row per patient (all joins happen here) |
| `multibridge/expected.py` | destination fields from an example output + optional rules overlay |
| `multibridge/aiview.py` | what the model may see: masked samples, number summaries, cleared categories only (default deny) |
| `multibridge/proposer.py` + `ai/ollama.py` | local AI proposer: prompt, JSON schema of real columns, checks on the reply, second pass with thinking, rules fallback. Loopback only |
| `multibridge/concepts.py` + `matcher.py` | rules proposer (offline fallback) and the format rules the AI proposer reuses |
| `multibridge/recipe.py` | draft → approved recipe, hash, who changed what, reuse by structure |
| `multibridge/engine.py` | applies a recipe row by row with fixed transforms and validates the result |
| `expected/` | `cdss_paciente.example.json` (the hackathon's `destino_expected.json`) + `.rules.json` |
| `examples/` | synthetic data for the 3 hospitals plus messy variants (`build_examples.py` regenerates them) |
| `tests/` | per area, plus the 3-hospital golden test (`tests/golden/`). The AI tests use a fake model, so no Ollama is needed |
| `scripts/eval_proposer.py` | rules vs local models against the reviewed plans → [docs/EVAL.md](docs/EVAL.md) |
| `docs/` | [ROADMAP](docs/ROADMAP.md) (start here), [COMPLIANCE](docs/COMPLIANCE.md), [JEV](docs/JEV.md) |

## Plugging in JEV (or any other normalizer)

Implement `normalize(text) -> list[ConceptMatch]` from `multibridge/terms/base.py` and register it
in `multibridge/terms/__init__.py`. The profiler, CLI and tests use whatever normalizer is
registered, so nothing else changes.

## Privacy and the law

Real patient data is health data under the GDPR. [docs/COMPLIANCE.md](docs/COMPLIANCE.md) lists every
legal constraint (GDPR, LOPDGDD, Ley 41/2002, ENS, NIS2, AI Act, MDR) as a numbered, testable
requirement with its status. In short:
- development uses synthetic data only
- real data stays inside the hospital
- the AI is local and sees structure plus fake samples, never real identifiers
- a human approves every mapping

## Honest limits

- `terms/seed_es.py` is a **demo seed** of about 30 ICD-10 categories. Before real use, load the
  official CIE-10-ES release and/or SNOMED CT (free in Spain as a SNOMED member country).
- Fuzzy `similarity` is a string similarity, **not a calibrated probability**. Calibration
  needs a labelled evaluation set (see the design doc).
- The proposer's `confidence` is a rules similarity, **not a calibrated probability** either.
- Not supported yet: key-value rows (HL7 `OBX-5` / FHIR `Observation.value`, where the code says
  whether a row is weight or height). The matcher marks them *pending* instead of guessing.
  Splitting a combined "Nombre y apellidos" column is not supported either.
- Review means editing the draft recipe JSON for now. The Streamlit review table is roadmap phase 3.
- All data in `examples/` is synthetic.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md): current state, decisions, and the next phases:
1. simplify to the hackathon design
2. local Qwen proposer
3. Streamlit review UI
4. harder data
5. evaluation and calibration
6. deployment
