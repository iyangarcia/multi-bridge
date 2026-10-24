# Multi Bridge — a data translator from any format to any format

> Show it one example of how you want your data. It maps the rest, a human approves, and a
> deterministic engine does the transformation.

Started at **Hackathon TalentUO 2026** (Reto 5, Pragmatech AI Solutions, Grupo 5). The challenge was to connect one clinical
application to three hospitals that speak HL7 v2.3, HL7 FHIR and Excel, **without writing one
integration per hospital**.

The project is now becoming a **translator for any type of data** (docs/ROADMAP.md, section 2a):

- **A generic core** knows formats and structure only.
- **Format plug-ins** (`multibridge/formats/`) read, write and check each format.
- **Domain packs** (`multibridge/packs/`) say what a domain's data means. Healthcare is the first
  pack, and everything below is what it does today.

A destination without a pack still works, matching on names, types and formats.

## Why this is harder than renaming columns (the clinical pack)

Mapping `F. Nacimiento` → `birthDate` is the easy part. Real hospital data breaks in many ways:

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
| **Repeated structures** | HL7 `PID-3` with DNI and NHC as repetitions; weight and height in `OBX` rows or FHIR Observations | selector columns pick by code: `PID-3.1 [PID-3.5=MR]`, `OBX-5 [OBX-3.1=29463-7]` (LOINC), with the unit from `OBX-6` |
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
hospital" claim, expressed in code. What a record is, and which tables join into it, comes
from the format plug-in; what the fields mean comes from the destination's pack.

## Try it

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # macOS/Linux: .venv/bin/pip
multibridge inspect examples/hospital_c_messy.xlsx
multibridge inspect examples/huca_oviedo_hl7v23.hl7 --as-ai
multibridge terms "DM2 mal controlada" "sospecha de NAC" "AP de IAM; HTA" "IRA" "DiabA"
pytest
```

### The review web app

```bash
multibridge serve            # then open http://127.0.0.1:8766
```

Your team's hackathon site, now wired to the real pipeline:
1. pick the source (any format) and the destination: one from `expected/`, a synthetic one, or
   upload an example of the output (plus its `.rules.json` if it has one)
2. choose who proposes (rules, or local `qwen3:8b` / `qwen3:30b`)
3. review each field with a before → after preview from the engine, its reasons and warnings,
   and decide which unused source columns to carry through
4. sign with your name, approve, and download the data in the destination's format, checked

**"Lo que ve la IA"** shows, next to your real values, exactly what the model receives. The server
listens on 127.0.0.1 only, and uploads stay in memory.

### Any destination: show an example of the output

The destination is an **example of the output in its own format**: `expected/<name>.example.json`
(the original), or a CSV, Excel, XML or FHIR file. `examples/destinos/` has three synthetic ones.
The output is written like the example: same columns or nesting, same date and decimal style, the
same fixed values (a FHIR Bundle's systems, codes and statuses). An optional `<name>.rules.json`
adds what an example can't show: required fields, allowed values, `"$pack"`, and `"$group_by"` to
turn many rows into one item (order lines → one order with its lines).

```bash
multibridge map examples/huca_oviedo_hl7v23.hl7 --model rules --expected examples/destinos/paciente_fhir.example.json
multibridge approve recipes/drafts/huca_oviedo_hl7v23.json --by "Your name" --carry ZPA-2 --expected examples/destinos/paciente_fhir.example.json
```

At approval every unused source column is either **carried** (`--carry`, or "Llevar" in the web
app) into the destination's slot for extras (a FHIR extension, an extra column, an XML element)
or **dropped**, and the recipe records which and who decided.

### Or just pick a format (no example)

In the web app, "…o elige solo el formato" turns any source into **JSON, CSV, Excel or XML**
without an example. With "Recibir todos los campos del archivo" every source column becomes a field
with its own name; the "Campos del destino" list lets you rename, retype, leave out or add fields
(added fields are proposed from the source by name). Dates come out as ISO dates and decimals as
numbers; anything that could go wrong as a number (postcodes, IDs, phones, codes) stays text. FHIR
and HL7 v2 still need an example, since their shape comes from the standard.

A field list lives in memory until you save it ("Guardar formato"). The **Formatos de destino** page
lists every format and lets you create one from scratch (or from the column names of any file),
edit, rename or delete it; saved lists go to `expected/<name>.fields.json` with names and types
only, and the CLI accepts them as `--expected`.

### The two first translations (phases 7 and 8)

- **Messy Excel → FHIR Bundle** (`expected/paciente_resumen_fhir.example.json`): each row becomes a
  Patient, its weight and height Observations (LOINC + UCUM), and one Condition per diagnosis and one
  AllergyIntolerance per allergy ("HTA; DLP" → two Conditions), all linked by reference. A
  "Nombre y apellidos" column is split into given name and two surnames. Diagnoses stay as the
  source wrote them (`code.text`): no code is invented. Try it with `examples/hospital_c_messy.xlsx`.
- **CSV order lines → nested JSON or XML** with no domain pack (`examples/pedidos/`,
  `examples/destinos/pedido_*.example.*`): lines are grouped into orders with a customer and their
  lines. With no vocabulary, columns are matched word by word ("NIF cliente" → `cliente.nif`,
  "Num. pedido" → número); guesses ("% Dto.", "Cliente") wait for the reviewer.

```bash
.venv/Scripts/python scripts/translations.py     # scores + checked output → docs/TRANSLATIONS.md
```

### How far to trust a confidence (phase 9)

`evalset/` generates messy files from invented records whose correct output is known: patients in CSV,
Excel, JSON, XML, HL7 v2 and FHIR, and order lines (no pack) in CSV, Excel, JSON and XML. Each proposal
is graded by the values it would really write. The score bands are then calibrated on one set of files
and checked on another, and the review screen shows what each confidence has meant in those tests ("en
pruebas sintéticas, propuestas así acertaron 96 de cada 100"). Real exports can be harder than the
generator, and the screen says so.

```bash
.venv/Scripts/python scripts/calibrate.py        # 1200 files → docs/CALIBRATION.md + multibridge/calibration.json
```

### Map a hospital file onto the destination (command line)

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
probabilities**, until they are calibrated (roadmap phase 9).

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
| `multibridge/formats/` | **format plug-ins**: reader, destination (targets + template from an example), writer, checker, what one record is, which structures repeat by code. CSV, Excel, JSON, XML, FHIR (all read and write), HL7 v2 (read) |
| `multibridge/output.py` | the output item shared by the engine and the writers (groups, extras, rendering like the example) |
| `multibridge/parsers/` | the readers behind them: `hl7v2` (no dependency), `fhir` (+ NDJSON, plain JSON), `csv_`, `excel`, `table` (finds tables in messy grids) |
| `multibridge/packs/` | **domain packs**: vocabulary, personal-data hints, code tables, terminology, special cases. `packs/clinical/` holds all the healthcare knowledge, including `terms/` (diagnosis text → ICD-10) |
| `multibridge/model.py` | `Dataset` and `Field`: the shape every reader produces |
| `multibridge/profile.py` | per field: type, format, unit, personal data (core detectors + every installed pack's); `as_ai()` |
| `multibridge/records.py` + `selectors.py` | one flat row per record (all joins happen here), plus selector columns that pick a repetition or row by its code |
| `multibridge/expected.py` | destination fields from an example of the output in any format + optional rules overlay (`"$pack"`, `"$group_by"`...) |
| `multibridge/aiview.py` | what the model may see: masked samples, number summaries, cleared categories only (default deny) |
| `multibridge/proposer.py` + `ai/ollama.py` | local AI proposer: prompt, JSON schema of real columns, checks on the reply, second pass with thinking, rules fallback. Loopback only |
| `multibridge/concepts.py` + `matcher.py` | rules proposer (offline fallback): evidence from the pack's vocabulary, or names when there's no pack, and the format rules the AI proposer reuses |
| `multibridge/recipe.py` | draft → approved recipe, hash, who changed what, reuse by structure |
| `multibridge/engine.py` | applies a recipe row by row with fixed transforms, validates, groups rows into items, carries extras; `Result.write()` gives the destination file |
| `multibridge/api.py` + `web/` | local API (loopback only) and the review web app, adapted from the hackathon site (Grupo 5), client branding removed |
| `expected/` | `cdss_paciente.example.json` (the hackathon's `destino_expected.json`), `paciente_resumen_fhir.example.json` (the phase 7 FHIR Bundle), each with its `.rules.json`; saved field lists (`*.fields.json`) |
| `examples/` | synthetic data for the 3 hospitals plus messy variants (`build_examples.py` regenerates them) |
| `tests/` | per area, plus the 3-hospital golden test and the Excel → FHIR golden Bundles (`tests/golden/`). The AI tests use a fake model, so no Ollama is needed |
| `scripts/eval_proposer.py` | rules vs local models against the reviewed plans → [docs/EVAL.md](docs/EVAL.md) |
| `examples/hard/` + `scripts/hard_data.py` | five hard files rendered from the same invented patients, with known answers → [docs/HARD_DATA.md](docs/HARD_DATA.md) |
| `examples/pedidos/` + `scripts/translations.py` | the non-clinical order lines (known answer) and the measurement of both first translations → [docs/TRANSLATIONS.md](docs/TRANSLATIONS.md) |
| `evalset/` + `scripts/calibrate.py` | phase 9: generated messy files with known answers, grading by output values, calibrated confidence bands (`multibridge/calibration.json`) → [docs/CALIBRATION.md](docs/CALIBRATION.md) |
| `docs/` | [ROADMAP](docs/ROADMAP.md) (start here), [COMPLIANCE](docs/COMPLIANCE.md), [JEV](docs/JEV.md) |

## Plugging in a format, a domain, or JEV

- **A format:** subclass `Format` in `multibridge/formats/` (read, write, check, and optionally
  what one record is) and add it to `FORMATS`.
- **A domain:** subclass `Pack` in `multibridge/packs/` and register it. Every hook has a no-op
  default, so a pack can start as just a vocabulary.
- **A normalizer (JEV, a terminology server):** implement `normalize(text)` (`multibridge/terminology.py`)
  and return it from the pack's `normalizer()`; for the clinical pack, register it in
  `multibridge/packs/clinical/terms/__init__.py`. Nothing else changes.

## Privacy and the law

[docs/COMPLIANCE.md](docs/COMPLIANCE.md) lists every legal constraint as a numbered, testable
requirement with its status. It has a general part (GDPR, LOPDGDD, ENS, NIS2, AI Act) for any
personal data, and a health part (Ley 41/2002, MDR, EHDS) for the clinical pack or any file where
health data is detected. In short:
- development uses synthetic data only
- real data stays inside the organisation
- the AI is local and sees structure plus masked samples, never real identifiers
- personal data is detected in every domain, with or without a pack
- a human approves every mapping

## Honest limits

- `packs/clinical/terms/seed_es.py` is a **demo seed** of about 30 ICD-10 categories. Before real use, load the
  official CIE-10-ES release and/or SNOMED CT (free in Spain as a SNOMED member country).
- Fuzzy `similarity` is a string similarity, **not a calibrated probability**. Calibration
  needs a labelled evaluation set (see the design doc).
- The proposer's `confidence` is a rules similarity, **not a calibrated probability** either.
- Splitting a combined "Nombre y apellidos" column is not supported yet: the matcher marks it
  *pending*.
- Writers and checkers exist for JSON, CSV, Excel, XML and FHIR; not for HL7 v2 yet. The FHIR
  checker covers structure, references and a few required elements, it is not the official
  validator. Without a pack, only fields with near-identical names are matched by the rules; the AI
  proposer helps more there.
- Repeated groups are one level deep, and a template has a fixed number of parts per item (one
  AllergyIntolerance per allergy in a list isn't supported yet).
- In the web app you can change a field's column, but not edit its transforms (a translation table, a date format) yet. For that, edit the draft recipe JSON.
- All data in `examples/` is synthetic.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md): current state, decisions, and the phases:
1. simplify to the hackathon design
2. local Qwen proposer
3. review UI: the hackathon website wired to a local API
4. harder data
5. generic core + clinical pack
6. destination from any example + writers
7. first translation: messy Excel → FHIR
8. second translation: CSV → nested XML or JSON
9. evaluation and calibration
10. deployment as a portfolio project: CI (done), a GitHub Pages demo running the Python in the browser
