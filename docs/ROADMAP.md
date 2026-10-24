# Roadmap and handoff

*The single place that says where the project is, what was decided, and what to do next.
Written so that someone (or an AI session) with no memory of earlier conversations can continue.
Last updated: 2026-10-23. **Direction changed to an any-to-any translator (section 2a);
phases 5 (generic core + clinical pack) and 6 (destination from any example + writers) done**,
next is phase 7.*

## 0. Read this first (new session checklist)

1. Read this file, then [COMPLIANCE.md](COMPLIANCE.md) (legal constraints C1–C19), then
   [JEV.md](JEV.md) (what "JEV" means), then the [README](../README.md).
2. Run the tests: `.venv/Scripts/python -m pytest -q`. They must pass before and after your changes.
3. Read section 2a: the project is now a **translator from any format to any format**, not a
   hospital mapper. Phases 5–8 are done (6b and 6c too). Open next steps, the user's pick: measure
   qwen3:8b on the translations (`scripts/translations.py`, needs Ollama), ICD-10 coding with C10,
   the HL7 v2 writer, nested groups, phase 9. Update the checkboxes and the
   session log (section 8) as you go.

## 1. Hard rules (non-negotiable)

- **No git.** Never commit, push or run git commands, and don't suggest it. The user manages GitHub
  (`CLAUDE.md`).
- **The hackathon folder is read-only reference:** `C:\Users\Usuario\Desktop\TalentUO 2026 Grupo 5`
  (original web app in `app/`, design docs `Mapeador_universal_IA.docx` and
  `Documentación mapeador.docx`). Don't modify it.
- **Synthetic data only** (C1). Never read, request or create real patient data, and, now that
  the project is not only clinical, no real personal data of any kind.
- **The AI is local** (C3): Ollama on `127.0.0.1:11434` only. No cloud model receives data. Jev
  only later, with structure only, and only if a hospital authorises it (C5).
- **A human approves every mapping** before it runs (C8). No score or model output skips approval.
- **Scores are labelled honestly.** Rule scores and model confidences are *uncalibrated* until
  phase 9. Never present them as probabilities.
- **The core assumes no domain** (D11, since phase 5). Nothing outside `multibridge/packs/` (domain
  knowledge) and the format plug-ins (`multibridge/formats/`, plus their readers `parsers/hl7v2.py`
  and `parsers/fhir.py`) may mention patients, hospitals, HL7, FHIR, LOINC or ICD-10.
  `tests/test_generic.py::test_core_has_no_clinical_terms` enforces it.
- Check [COMPLIANCE.md](COMPLIANCE.md) before touching data flow, the AI or storage. Never break a ✅ item.

## 2. The idea we're building (from the hackathon)

Reto 5 (Pragmatech AI Solutions, TalentUO 2026, Grupo 5): connect one clinical app to hospitals
that speak HL7 v2.3, FHIR and Excel **without writing an integration per hospital**.

> *"Enséñale un ejemplo de cómo quieres los datos y la IA hace el resto."*

The user does three things:
1. **Uploads the destination:** an example of how the data should look (JSON, Excel template).
   That *is* EXPECTED.
2. **Uploads the source:** the file they have (CSV, Excel, JSON/FHIR, HL7 message).
3. **Reviews a table** the AI proposes ("this column goes to that one", with a traffic-light
   confidence), corrects it, presses **Approve**, and downloads the transformed data.

The approved mapping is saved as a **recipe**. When a file with the same structure arrives later,
the system recognises it and applies the recipe **without calling the AI**.

Rules from the hackathon design:
- A human always approves.
- Every target field is explicitly "mapeado", "sin dato" or "pendiente". Approval is impossible
  while anything is pending.
- Unmatched source and target fields are listed.
- **The AI never touches the data**: it only proposes; a deterministic engine transforms.
- Per-company learning: approved recipes become examples for future proposals, with no model
  retraining.

Hackathon list of transforms: copy, rename, date conversion, translate values (H/M →
male/female), join or split columns.

## 2a. Direction (decided 2026-10-22): a translator from anywhere to anywhere

Phases 1–4 built a **mapper**: many hospital formats in, one fixed clinical JSON out
(`cdss_paciente`). The goal of the application is a **translator**: any type of data, in any
format, into any other type of data in any other format. The hackathon idea still holds and
becomes general: *show an example of the output you want, in any format, and the system proposes
how to fill it from any input.*

The user's decisions:
- **A generic core with clinical as the first domain pack.** This keeps the hackathon story, the
  hard test files and the work already done, while nothing in the core assumes healthcare.
- **Prove "any to any" early with two first translations** that differ in both domain and
  structure:
  - **Messy Excel → FHIR:** clinical pack, flat table to a standard message (phase 7).
  - **CSV → nested XML or JSON:** no pack, a generic case (phase 8).

### The architecture

| Part | What it is | Today |
|---|---|---|
| **Format plug-ins** | One per format: a **reader** (file → generic tree of `path → value` with repeats), a **writer** (the reverse) and a **checker** (is the output valid for that format?). Adding a format is one plug-in, never one mapping per pair of formats | readers exist for CSV, Excel, JSON/FHIR, HL7 v2; the only writer is the clinical JSON |
| **Generic data model** | Records of `path → value`, repeats as lists, selector columns (`X [code=Y]`). A *structure*, not a vocabulary, so nothing is lost on the way through, custom fields included | `records.py` + `selectors.py`, but "one row per patient" is built in |
| **Destination from an example, in any format** | The example goes through its own reader to give the target fields, types and formats; an optional overlay adds meaning and rules (like `.rules.json`) | JSON example only (`expected.py`) |
| **Domain packs** (optional) | Vocabulary, synonyms, sensitive categories, code tables, terminology transforms, domain checks. **Clinical** = today's `concepts.py`, `terms/`, the LOINC/HL7 tables in `selectors.py`, the medical synonyms. Without a pack, matching relies on names, profiles and the AI: more fields stay pending, but it works | clinical knowledge is spread through the core |
| **Connectors** | *Where* data comes from or goes to (files first; databases, SFTP, HTTP APIs later), separate from *what shape* it has | files only |

**Unchanged:** profiling, the proposer (rules, local Qwen, later Jev), recipes with human approval,
the engine's fixed transforms, the review web app and its privacy rules.

**Not chosen, and why:**
- A fixed middle format (everything → FHIR or one canonical model → everything): it loses
  whatever the middle model doesn't cover, custom fields first. The clinical vocabulary stays
  a *matching aid* inside the clinical pack, not a format the data passes through.
- Fixed standard-to-standard conversions (e.g. only HL7 v2 → FHIR): predictable, but it drops the
  learn-from-an-example idea, and existing tools already do it (NextGen/Mirth Connect, Microsoft
  FHIR-Converter).
- Reversible recipes only: round trips between pairs already mapped, not a translator.

### Custom fields (both sides)

- **In the source** (a private Excel column, an HL7 Z-segment, a FHIR extension): readers already
  read them as ordinary columns. **None is ever dropped silently.** In review each unmatched one
  gets a decision, saved in the recipe:
  - **map** it to a destination field;
  - **carry it through** in the destination format's slot for extras:
    - FHIR: an `extension` with a configurable base URL, or an `Observation` with a local code system
    - HL7 v2: a Z-segment or an `OBX` with a local code
    - CSV / Excel / JSON / XML: an extra column, key or element
  - **drop** it on purpose; the recipe records who dropped it and the output report lists it.
- **In the destination** (a field like `riesgo_caidas` that matches no standard): described by its
  example value plus an optional overlay entry, as today.
- **Matching:** no vocabulary knows them, so the rules have only the name and profile. This is
  where the AI helps most (with masked samples). Custom fields always start as **pending**; once
  approved, the recipe reuses the match for files with the same structure.
- **Privacy:** free-text custom fields may hold personal or health data. Sensitive-data detection
  and the default-deny AI view apply to them as to any field, and data carried through an extension
  or Z-segment is still personal data and appears in the output report.

### Honest limits on "any"

- **Structured data** (tables, trees, messages): fully covered by plug-ins.
- **Standards with built-in meaning** (HL7, FHIR, EDI): covered, but each needs a solid checker.
  Writing HL7 v2 is the hardest and comes after FHIR.
- **Unstructured data** (PDFs, scans, free text): a different problem. Extracting values relies on
  the AI and is less reliable. Later, and always through review.
- **Cardinality** is the main new difficulty: one source row may become many output items (an Excel
  row → a Patient plus several Observations) and many rows may become one (CSV order lines → one
  nested order).

## 3. Environment

| | |
|---|---|
| Machine | Windows 11, i7-14650HX, 32 GB RAM, RTX 4060 Laptop **8 GB VRAM** |
| Python | 3.13, venv in `.venv/` (`.venv/Scripts/python`, `.venv/Scripts/multibridge`) |
| Dependencies | `openpyxl`; dev: `pytest`. Prefer the standard library (for example `urllib` for Ollama) over new packages |
| Ollama | 0.40.6, running on `127.0.0.1:11434`, `OLLAMA_HOST` unset (keep it that way) |
| Models | `qwen3:8b` (5.2 GB, fits entirely on the GPU) and `qwen3:30b` (18 GB, mixture of experts with ~3B active parameters, split GPU+RAM). On this laptop both run at similar speed |

## 4. Current state (written after phase 1, 2026-10-21)

*Since then: phases 2–4 added the local AI proposer, selector columns and the web app. Phase 5
split the code into a generic core, format plug-ins (`formats/`) and domain packs (`packs/`, with
`packs/clinical/` holding everything clinical: `concepts.py`'s vocabulary is now
`packs/clinical/vocabulary.py`, `terms/` is `packs/clinical/terms/`). 179 tests pass. The table
below describes the pipeline, which is unchanged in behaviour.*

The pipeline follows the hackathon design:

| Module | What it does |
|---|---|
| `parsers/` (`hl7v2`, `fhir`, `csv_`, `excel`, `table`) | any format → `Dataset` of tables + `Field`s. The user confirmed this is right |
| `profile.py` | types, formats, units, sensitive-data detection, `as_ai()` levels 1–2 (level 3 is phase 2) |
| `terms/` | diagnosis text → ICD-10 (qualifiers, abbreviations, ambiguity), `Normalizer` interface |
| `records.py` | `to_rows(ds)` → `Rows`: one flat row per patient. **All joins live here.** Columns = source paths (`PID-5.1`, `name.family`, `AllergyIntolerance.code.text`, `Peso (kg)`); repeated values are lists |
| `expected.py` | `Expected.load("expected/cdss_paciente.example.json")`: targets + types from the example, plus the `cdss_paciente.rules.json` overlay (required, enum, pattern, range, unit, case, multiple). `Expected.id` = name + fingerprint; changing either file invalidates old recipes |
| `concepts.py` + `matcher.py` | rules proposer (the offline fallback): `propose(rows, expected)` → draft recipe |
| `recipe.py` | recipe format (see its docstring), `new` / `problems` / `approve` (records `changed_by` against the frozen `proposal`) / `verify` (sha256) / `compatible` / `find` |
| `engine.py` | `run(rows, recipe, expected)` → `Result(records, rejected, report)`. Fixed transforms only, no joins, no values in the report |
| `cli.py` | `inspect`, `terms`, `expected`, `map`, `approve`, `run`. Default destination `expected/cdss_paciente.example.json`, recipes in `recipes/` (drafts in `recipes/drafts/`) |
| `tests/golden/` | reviewed plans (`plans/`) and the 24 reviewed output records (`output/`) for the 3 hospitals. Regenerate only deliberately: `tests/golden/build_golden.py` |

**The shape any proposer must produce** (rules today, Qwen in phase 2): call
`recipe.new(name, rows, expected, fields, proposed_by="qwen3:8b")` with, per target path,
`{"status": "mapped"|"no_data"|"pending", "from": [columns], "transforms": [...], "confidence": float|None,
"why": [...], "issues": [...]}`. The transform names are listed in `engine.py`'s docstring.

Leftover: a `drivers/` folder in the repo root holds one draft in the *old* format, from the user
trying `map` before phase 1. It is unused; the user can delete it.

## 5. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Parsers, profile, `as_ai`, `terms/` stay | agreed |
| D2 | **Joins move out of the engine.** A records step turns each source into **one flat row per patient** (HL7: one row per message, segments side by side, repeated segments as lists; FHIR: a Patient plus its referenced resources; CSV/Excel: one row each). The engine then only applies a recipe row by row | approved by the user 2026-10-21; implemented in phase 1 |
| D3 | **EXPECTED = an example file.** Target fields are read from an example output (`expected/cdss_paciente.example.json`, a copy of the hackathon's `destino_expected.json`; Excel template later). Constraints (allowed values, required fields) are an optional small overlay, not a hand-written contract | approved by the user 2026-10-21; implemented in phase 1 |
| D4 | **Recipe** = small JSON: per target, `{sources, transform(s), status, confidence, proposed_by, changed_by}` plus approval (who, when, plan hash) and a structure signature for reuse. Provenance per field satisfies C9 | approved by the user 2026-10-21; implemented in phase 1 |
| D5 | **The local AI proposes** (Qwen via Ollama). The rules matcher stays only as the offline fallback | agreed |
| D6 | Ollama calls: `"think": false` by default, a second pass with `"think": true` only for low-confidence or pending fields; `"keep_alive": 0`; `format` = JSON schema whose enums list the real source fields and allowed transforms; never save thinking traces | agreed |
| D7 | `qwen3:8b` is the baseline the project must work with (hospital servers are weaker); `qwen3:30b` is the strong tier. Choose by measuring against the golden plans, not by feel | agreed |
| D8 | What the AI sees: level 3 = *shape-preserving fake samples* for sensitive columns; real values only for columns cleared as harmless categories (default deny, C6); free text sent as normalised concepts, not raw text | agreed |
| D9 | Jev later, behind an interface copying its choice/score/noul primitives (rules / local / jev backends), structure only | agreed |
| D10 | **The review UI is the hackathon website, reused, not Streamlit.** Copy it from `TalentUO 2026 Grupo 5/app/` into `web/` (the hackathon folder stays untouched). Remove client branding. Replace its JavaScript parsers and simulated AI with calls to a small local Python API, so there is one implementation of the logic. See phase 3 | started at the user's request 2026-10-22 and implemented (phase 3). Client branding removed; Grupo 5 credited. Grupo 5 is OK with the reuse (user, 2026-10-24) |
| D11 | **Generic core + domain packs.** The project is a translator from any format to any format (section 2a). The core knows formats and structure only; clinical knowledge moves into the first domain pack | approved by the user 2026-10-22 |
| D12 | **First translations: messy Excel → FHIR** (clinical pack) **and CSV → nested XML or JSON** (no pack). They differ in domain, direction of cardinality and output shape, so together they prove "any to any" | approved by the user 2026-10-22 |
| D13 | **Format plug-in = reader + writer + checker**, registered by format; no code per pair of formats. Extends D3: EXPECTED is an example in *any* format, read by its own reader | approved by the user 2026-10-24 |
| D14 | **No custom field is dropped silently**: each unmatched source field is mapped, carried through (FHIR extension / HL7 Z-segment / extra column) or dropped on purpose, recorded in the recipe (C9) | approved by the user 2026-10-24 |
| D15 | **Compliance splits in two:** general GDPR rules for every domain (sensitive categories detected everywhere), plus the health rules whenever the clinical pack is used or health data is detected | approved by the user 2026-10-24 |

## 6. Phases

### Phase 1: simplify to the hackathon design (records, recipe, engine) — done 2026-10-21
- [x] D2–D4 approved by the user.
- [x] `records.py`: flat rows per patient, tests in `tests/test_records.py`.
- [x] `expected.py` + `expected/cdss_paciente.example.json` + `.rules.json`. Fixed on the way:
      target concepts come from the leaf name (`direccion.ciudad` was read as a street).
- [x] `recipe.py`: approval hash, automatic `changed_by`, reuse by structure.
- [x] `engine.py` rewritten: no joins; multiple values resolved by an explicit `first`/`join_values`
      or the target's `multiple` rule, otherwise an error.
- [x] Golden ported: the same proposal decisions, and the 24 output records are byte-identical.
      The one plan difference: HUCA's allergy needs no explicit `join_values`, because no message has
      two AL1 (the target's `multiple: join` covers it if one does).
- [x] Removed `contract.py`, `driver.py`, `contracts/`. CLI and README updated.

### Phase 2: local AI proposer (in progress, 2026-10-21)
- [x] `multibridge/ai/ollama.py`: standard-library client.
      - Loopback only (refuses any other host).
      - `think` flag, `keep_alive` + `unload()`, temperature 0, `format` = JSON schema.
      - **`num_ctx` 12288 and `num_predict` caps.** With Ollama's default ~4k context, a real file's
        prompt plus answer overflowed and qwen3:8b ran for 10 minutes until the timeout.
      - Answers cut off at the length limit are rejected.
- [x] `multibridge/aiview.py` (replaces the "synthetic fakes" idea). Values are **masked**:
      `FERNANDEZ` → `XXXXXXXXX`. Measurements are sent as min/median/max, diagnoses as a terminology
      summary, real values only for cleared categories (default deny, C4, C6). Destination example
      values are masked too.
- [x] `multibridge/proposer.py`. **The model picks columns, the code picks formats**: transforms
      come from `matcher.transforms_for`; the model may add translations, only into allowed values.
      - Checks on the reply: unknown or unoffered columns, the same column twice, a column used for
        two fields, required fields left as no_data. Anything dubious becomes pending.
      - Cross-check with the rules (`_conflict`): a chosen column that clearly means something else
        (FHIR technical `id`, a full-name column for the first name, a diagnosis for the doctor)
        becomes pending. If the model says no_data but the rules see a strong candidate, the field
        becomes pending with that suggestion.
      - FHIR metadata columns (`.system/.use/.type`) are never offered to the model.
      - The code puts name parts in output order (given name first).
      - A second pass with thinking runs for doubtful fields. If Ollama is down and the model is
        "auto", it falls back to rules.
- [x] Tests with a fake model (`tests/test_proposer.py`), including replays of every mistake seen
      in the evaluation and privacy checks on the prompt for all six example files. 134 tests pass.
- [x] CLI: `multibridge map FILE --model auto|rules|qwen3:30b` (default auto).
- [x] First evaluation (before the cross-checks), saved in `docs/EVAL.md` history below:
      - On the 3 reviewed hospitals: rules 45/45, **qwen3:8b 44/45**, qwen3:30b 43/45.
      - Time per file: 8b 28–60 s, 30b 73–193 s.
      - Mistakes: 8b invented León's absent doctor from `id + identifier.system ×2`, and the
        conditions file's postal code from `identifier.system ×2`. 30b said the CSV had no phone,
        and took the FHIR technical `id` as the patient id. Both models put "Nombre y apellidos"
        into the first-name field.
      - **Pattern: when a field has a source, the 8b finds it; when it has none, it invents one with
        confidence 1.0.** Its self-reported confidence is not informative.
      - Each of these mistakes now has a check (above) and a replay test.
- [x] **Re-run `scripts/eval_proposer.py rules qwen3:8b` with the checks in place** (2026-10-24):
      qwen3:8b 15/15 on all three hospitals, 0 wrong. qwen3:30b not re-run: the user said there is
      no need yet (2026-10-24); its old rows stay in `EVAL.md`, marked "not re-run". Ask the user
      before starting Ollama.
- [ ] Record the model digest (exact version) in recipes (C9, C15).
- **Done when:** the re-run shows no *wrong* fields for qwen3:8b on the 3 reviewed hospitals
  (pending is acceptable), and `EVAL.md` documents every difference.

### Phase 3: review UI: the hackathon website, wired to the Python pipeline (D10) — done 2026-10-22
`multibridge serve` → http://127.0.0.1:8766. Started at the user's request ("start phase 3").
- [x] Read the hackathon site. It had a JavaScript copy of the pipeline (`parsers.js`, `matcher.js`
      simulated AI, `generarSalida` engine) and kept everything in `localStorage`.
- [x] Copied into `web/` (the hackathon folder untouched). Kept the HTML structure, `styles.css`, the
      Multi Bridge icons (`img/icono.png`, `img/logo.png`), the plain-language field names and the
      review flow. **Removed:**
      - the client branding (Pragmatech logo `cliente.png`, `config.js`)
      - `parsers.js`, `matcher.js`, `ejemplos.js`, the JS engine and the `localStorage` "model"
- [x] `multibridge/api.py` (standard library):
      - loopback only, plus a Host-header check against DNS rebinding
      - static files only from `web/`; no request logs
      - uploads in memory only (last 10)
      - endpoints `health, expected, examples, recipes, upload, propose, field, approve, run`
- [x] **The server keeps its own copy of each proposal.** On approval the browser sends only the
      decisions: `proposal`, `proposed_by` and the reuse signature are rebuilt server-side, so
      provenance can't be forged and reuse checks the columns actually approved.
- [x] Mapping screen centred on the destination fields (like recipes):
      - before → after preview from the real engine, reasons, warnings, custom / personal-data badges
      - change column (suggested first, then all)
      - bulk-accept only high-confidence fields *without warnings*
      - "Lo apruebo" for pending fields (recorded as a human change)
      - required fields can't be skipped; the reviewer's name is required
      - recipe reuse notice; proposer selector (rules / qwen3:8b / qwen3:30b, disabled if Ollama is off)
      - **"Lo que ve la IA" vs "Tus datos" panel**
- [x] Start page from `/api/recipes`; "Tu formato" read-only from `expected/`.
- [x] `tests/test_api.py` (9 tests): flow, loopback, Host check, path traversal, forged provenance,
      approval rules, column change preview, masked AI view.
- [x] Browser check: HUCA proposed → 11 bulk-accepted + 4 reviewed → approved → 8/8 converted;
      reload offers reuse; hard FHIR file shows the phone tie as pending; phone width fixed
      (long names now wrap).
- [x] The 11 example buttons are a long list: group them (reto / difíciles) or use a select. Done in
      phase 6c (one grouped dropdown).
- [ ] No way yet to edit transforms (e.g. a translation table) in the UI, only the column.
- [ ] CLI `approve` still computes the reuse signature from the *proposed* columns, not the final
      ones (the API rebuilds it). Fix by passing the source file to `approve`, or reject edits
      to `from` in drafts.
- **Done when:** met. The three hospitals can be mapped, reviewed, approved and converted from the
  browser; there's no mapping logic in JavaScript; the API listens only on loopback.

### Phase 4: harder data (started 2026-10-22, no AI)
Hard-data test: `examples/hard/build_hard.py` renders the same three invented patients as five hard
files with known answers (`answers.json`); `scripts/hard_data.py` writes
[HARD_DATA.md](HARD_DATA.md); `tests/test_hard_data.py` locks the results in.
- [x] Five hard files: English CSV, cryptic Spanish CSV, HL7 v2.5, complex FHIR, hard Excel.
      **Pipeline with the correct recipe: exact on all five.**
- [x] Rules proposer on them: 73/75 right, **0 dangerous**. The two misses: `MED` left unmapped
      on purpose (in Spanish exports it can mean médico or medicación), and home vs mobile phone
      left as a tie for a human. Fixed on the way:
      - **bug:** a date column mixing shapes (HL7 `19601105` + `198504121030`; Excel real date +
        typed text) stopped being a date. It is now `format: "mixed"` + a `date` op with a list of formats
      - FHIR `name` and `telecom` are sliced by `use` (official vs nickname, home vs mobile);
        metadata paths include nested ones (`identifier[x].type.coding.code`), via `model.is_metadata`
      - joined columns: APE1 + APE2, HL7 PID-5.2 + PID-5.3; FHIR given names joined with a space
      - units read from the values when the label has none (height 1,68 → m, weight 65500 → g)
      - pending instead of guessing: near-ties, repeated identifiers in one HL7 field, measurements
        while Observation values exist, full-name columns
      - a `ubicacion` concept, so a room number (PV1-3.2) can't pass for a height
      - English and Spanish-abbreviation synonyms (mobile, address, allergies, GP, NOM, APE1, DOM,
        LOC, ALERG, FNAC...)
- [x] **Pick a repetition or a row by its code** (2026-10-22), as **selector columns**
      (`multibridge/selectors.py`, called from `records.to_rows`):
      - Columns such as `PID-3.1 [PID-3.5=MR]`, `OBX-5 [OBX-3.1=29463-7]`,
        `Observation.valueQuantity.value [Observation.code.coding.code=8302-2]`.
      - They are ordinary columns for the matcher, recipes and engine; **the engine is unchanged**.
      - The HL7 parser keeps each repetition whole (`rec["_reps"]`), so selection is exact per
        repetition / segment / resource.
      - Covered: PID-3 (CX.5 identifier type), PID-5 (XPN.7), PID-11 (XAD.7), PID-13 (XTN.2), NK1-2,
        OBX by OBX-3.1, FHIR Observation by code. Only data components get selectors (not PID-3.4
        authority); selectors identical to their base column are skipped.
      - Descriptions come from a small code table (LOINC, HL7 0203/0200/0201/0190); the unit comes
        from OBX-6 / valueQuantity.unit.
      - The matcher prefers one clean value per patient (−0.1 for multi-valued columns) and lightly
        penalises empty columns (−0.2 × null ratio).
      - Result: H3's NHC and DNI and H4's weight and height are now mapped exactly. Identifiers *without*
        a type code (`NHC~ASTU` with no PID-3.5) stay pending.
- [x] Split column: "Nombre completo" / "Nombre y apellidos" → given + family, with human review
      (Spanish names are hard: compound given names, two surnames, particles). Done in phase 7
      (`name_part`).
- [ ] Terminology transform: diagnosis text → ICD-10 via `terms/`, keeping the original text next
      to the code; every change approved (C10).
- [ ] Re-run the hard files with qwen3:8b (`proposer.propose`) once Ollama is back, to compare with
      the rules.

*The split-name and terminology tasks above now belong to the clinical pack (phase 5).*

### Phase 5: generic core + clinical pack (D11), no change in behaviour — done 2026-10-22
Started at the user's request ("start phase 5").
- [x] **Format plug-ins** (`multibridge/formats/`): a `Format` base class with `read`, `write`,
      `check`, `sniff` (detection by extension or content, same order as before), and the record
      rules `root` / `linked` / `column`, plus `keyed_entities` / `keyed_fields` / `unit_of` /
      `code_meanings` (selector columns) and `timestamp_types` / `coded_types` (declared types).
      Plug-ins: CSV, Excel, JSON, FHIR, HL7 v2; the existing parsers are their readers.
      **The JSON writer** (`formats.get("json").write`) now writes the CLI output, byte-identical;
      `check` validates a list of records. FHIR / HL7 writers raise NotImplementedError (phase 6).
- [x] **Generic records:** `records.py` and `selectors.py` take everything format-specific from
      the plug-in: HL7 roots on PID and joins by message, FHIR on Patient and joins by reference,
      others root on the widest table. The HL7/OBX/Observation tables moved into the plug-ins.
- [x] **Domain packs** (`multibridge/packs/`): a `Pack` base class whose hooks are all no-ops,
      chosen by the destination's overlay (`"$pack": "clinical"` in `cdss_paciente.rules.json`;
      not part of `Expected.id`). `packs/clinical/` holds the vocabulary and value detectors
      (`vocabulary.py`), `terms/`, the LOINC meanings, ICD-10 code shape, clinical personal-data
      hints, the clinical system prompt, and every special case from the hard files (doctor vs
      patient, nickname slices, diagnosis columns, observation values, shared identifiers, APE1 +
      APE2, PID-5.2 + PID-5.3, units from values, name order, the AI cross-checks).
      `multibridge/terminology.py` is the core's normalizer contract.
- [x] **Personal-data detection split** (COMPLIANCE C20): core hints for ID documents,
      identifiers, names, contact, addresses, birth dates and **GDPR art. 9 categories**; core value
      patterns for DNI, NIE, phone, email, **IBAN** and **values shaped like people's names** (found
      while testing: without a pack, a "Cliente" column of names counted as harmless categories and
      would have reached the AI). The clinical pack adds NHC, health card, doctor's name and HL7
      positions. Profiling runs every installed pack's detectors (over-detection is the safe side).
- [x] **No pack** works: without vocabulary, a near-identical name (≥ 0.75 similarity) is evidence
      on its own, for targets no concept knows. `tests/test_generic.py` (8 tests): a shop CSV mapped
      with no pack (dates, decimal commas, an untranslatable status left pending), detection without
      packs, the clinical pack's extra hints, the format registry and JSON writer, and the grep test.
- [x] `docs/COMPLIANCE.md` rewritten along D15: section 0 says when each part applies; general
      and health parts for data and laws; constraints tagged (C10 is [health]); new C20; every ✅ kept.
- [x] Other core changes: the CLI and API take the destination from the only `expected/*.example.json`
      (or `--expected`); `multibridge terms` uses the destination's pack (`--pack`); the API's
      example extensions come from the plug-ins.
- [x] **Proof of no change in behaviour:** a snapshot of everything users and the model see (profiles,
      rows, proposals, rankings, AI prompts, system prompt) for all 12 example files is
      **byte-identical** before and after. The golden output is unchanged. Only two test imports
      changed (`terms` and `is_observation` moved into the clinical pack). Web app re-checked in the
      browser: HUCA 15/15 mapped by rules.
- [ ] Phase 4 leftovers, now clinical-pack tasks: split full-name columns; diagnosis text → ICD-10
      terminology transform (C10).
- **Done when:** met.

### Phase 6: destination from any example + writers (D13) — done 2026-10-23
Started at the user's request ("start phase 6").
- [x] **Destination from an example in any format** (`Expected.from_bytes` / `load`): the example's
      format plug-in gives a `Destination` (targets + a *template* for the writer + fixed values).
      `expected/<name>.example.<ext>` + optional `<name>.rules.json`. New overlay keys: `$group_by`,
      `$repeat` (XML), `$fixed` / `$targets` (FHIR), `$extension_base`. `Expected.id` includes the
      format and grouping **only when they differ from the original JSON**: `cdss_paciente#0ac41f7c`
      is unchanged, so earlier recipes keep matching (test).
      - **JSON:** objects nest; a list of objects is a repeated group (`lineas[].producto`, one level);
        a list of plain values is one target that takes several values (`multiple: "list"`).
      - **CSV / Excel:** the main table's columns in order; types, date style, decimal comma and number
        of decimals from the example's values; title case when the example writes "Ana Ruiz".
      - **XML** (new plug-in, reader too): one record per repeated child of the root; attributes as
        `@name`; an element the example repeats becomes a repeated group or a list. DOCTYPE/ENTITY
        refused.
      - **FHIR:** the example Bundle (or one resource) is a template. Data leaves are targets, named
        like the reader names them (`Patient.name.given`, `Observation[29463-7].valueQuantity.value`);
        structural leaves (resourceType, ids, references, systems, `use`, statuses, an Observation's
        code, UCUM unit) stay fixed. Targets get descriptions, units (`kg` from the template) and
        enums (`Patient.gender`), so the clinical pack matches them like any other destination.
- [x] **Output model** (`output.py`): flat items `{target path: value}`, repeated groups as lists
      of sub-items, carried fields under `_extras`; `nest()` gives the JSON view. The engine keeps
      `Result.records` (nested, byte-identical for the original destination) and adds `items` and
      `Result.write(expected)`.
- [x] **Cardinality:** many rows → one item with `$group_by` (fields outside the group must agree
      across its rows, otherwise those rows are set aside with the reason; a row without the key is
      set aside); one row → several parts through the template (a Patient + its Observations) or a
      list target. Both live in the destination, so they are part of `Expected.id` and of what the
      reviewer approves.
      - Not done: "selector columns backwards" for HL7 (writing PID-3 by type code) waits for the
        HL7 writer; for FHIR the template's code slices already create the right Observation.
- [x] **Writers + checkers**, standard library + openpyxl only, no new dependency:
      JSON (list of records); CSV (example's separator, BOM if it had one, extras as extra columns;
      checker: same width on every row); Excel (typed cells, real dates; checker: opens, has a
      header); XML (copies the example element by element, drops empty elements; checker:
      well-formed, no DOCTYPE); FHIR (new `urn:uuid` per item and resource, references rewired,
      resources whose targets are all empty left out, extras as `extension` with
      `$extension_base`; checker: resourceType, unique fullUrls, references inside the Bundle,
      required elements of Observation / Condition / AllergyIntolerance, gender, birthDate,
      numeric quantities). A full FHIR validator (Java) was not added.
- [x] **Custom fields (D14):** `approve(..., carry=[...])` records `extras: {carry, drop, by}` for
      every unused source column (dropping is a recorded decision, never silent). Part of the
      plan hash when present; old recipes without it still verify. The engine copies carried
      values; the report lists `custom_fields`. A carried column missing from a new file makes the
      recipe not reusable. CLI: `multibridge approve ... --carry COLUMN`.
- [x] **Clinical pack:** translations now land on the destination's own catalogue (`Hombre/Mujer`
      as well as `male/female`, `O+` from `0+`); `Pack.translate(..., allowed)`.
- [x] **Web app "De → A":** destination picker (folder, `examples/destinos/`, or **uploaded**: an
      example plus its optional `.rules.json`, kept in memory only); context line (pack, grouping,
      fixed values); "Llevar" per unused source column with a running "x extra, y descartados";
      the result shows the output file and its checker's problems; download in the destination's
      format. Wording made neutral (origen / destino); the home page keeps the hackathon hospitals.
      Server checks the approval is for the destination the proposal was made for.
- [x] **Bug found from phase 5:** `/api/field` (recomputing a field after a column change) ran
      without the destination's pack, so clinical translations disappeared after a change. Fixed,
      with a regression test.
- [x] Example destinations (synthetic) in `examples/destinos/`: FHIR Bundle (Patient + weight +
      height), CSV table (Hombre/Mujer, decimal comma), XML with a phone list.
- [x] `tests/test_destinations.py` (27 tests): every source × every destination (3 × 5) approved,
      run, written and checked; FHIR template, ids, references, empty resources; CSV looks like the
      example; grouping to JSON and XML (and the XML read back); rows of a group that disagree;
      list targets; carry/drop into every format; old recipes; DOCTYPE; the API flow with an
      uploaded destination. **206 tests pass**; the behaviour snapshot of the original destination is
      unchanged (only the three new, unset Target attributes appear).
- [x] Browser check: messy CSV → FHIR (8/8, 24 resources, check passed, blood group carried as an
      extension, 3 drops recorded); HL7 → CSV (Mujer/Hombre, 12/04/1985, 58,5) and HL7 → XML. Test
      recipes deleted afterwards.
- [ ] Not done: editing transforms in the UI (still only the column); HL7 v2 writer (later);
      variable fan-out (one AllergyIntolerance per allergy in a list); nested groups (one level only).
- **Done when:** met for JSON, CSV, Excel, XML and FHIR destinations (HL7 v2 writing is in "Later").

### Phase 6b: destination with no example — format + field list — done 2026-10-23
Asked by the user: in the web app you couldn't make your own format, and going "anything → JSON"
needed an example; it should be "press JSON + a box to receive every field of the file".
- [x] `Format.blank(fields)`: JSON (one key per field, the name as typed, no nesting on dots),
      CSV (`,` by default), Excel (sheet "Datos"), XML (`<registros><registro>`, names made valid
      tags: "Nº Historia" → `No_Historia`). FHIR and HL7 v2 still need an example (a standard
      message's shape can't come from a field list).
- [x] `Expected.from_fields(format, fields, name)` with checks (names, duplicates, types, at most
      500); same list → same `Expected.id`, so an approved recipe is reused for it.
- [x] `fields_from_rows(rows)` ("recibir todos los campos"): every non-empty column, typed only where
      no value can fail: dates → date; decimals → number; whole numbers only with a unit
      (postcode, bed, version "2.3", sequence numbers stay text); identifiers, personal data and
      format-declared codes stay text; datetimes stay text (no lost time); multi-value cells → list.
- [x] API: `GET /api/formats`, `POST /api/fields`, `POST /api/destination/fields` (memory only,
      `replace` to edit the same one). A field's `from` ties it to a column: the proposal takes it
      as decided (`proposed_by: "direct"`, only transforms worked out); fields added by hand are
      proposed by name; columns left out go through the usual carry/drop decision.
- [x] Web: "…o elige solo el formato" (JSON / CSV / Excel / XML) + "Recibir todos los campos del
      archivo"; a "Campos del destino" editor (receive or not, rename, type, required, add field,
      mark/unmark all, apply). Direct fields arrive already reviewed. Works before or after the
      source is loaded; switching format keeps the edits.
- [x] Fixed on the way: a CSV whose first header is `MSH-3` was read as HL7 (the sniff now needs
      `MSH|^~\&|`); a list target got `first` from the matcher and lost values; the server printed
      a traceback when the browser dropped a request (`ConnectionAbortedError`, now ignored).
- [x] `tests/test_field_list.py` (28 tests): 3 sources × 4 formats with every field, 8/8 rows,
      output checked and read back. **234 tests pass**; the behaviour snapshot is identical to
      phase 6. Browser check done (HL7 → JSON with renamed fields, Álvarez-Buylla → CSV → Excel);
      test recipes deleted.
- [ ] Not done: nesting from the field list (`cliente.nombre` → object), CSV separator choice in
      the UI, editing transforms.

### Phase 6c: "Formatos de destino" page — create and edit formats in the web app — done 2026-10-24
Asked by the user: too many synthetic-example buttons; rename "Destinos"; let formats be made and
changed from that page, not only by uploading a file in "Traducir datos".
- [x] Saved field lists: `expected/<name>.fields.json` (`{"format", "fields": [{name, type, required?,
      multiple?}]}`, structure only, no column ties, no values). `Expected.load` reads them, so the
      CLI takes `--expected expected/<name>.fields.json`. Listed after the examples, so the default
      destination is still `cdss_paciente`.
- [x] API: `save` + `name` on `POST /api/destination/fields` (409 on a taken name; `replace` edits or
      renames its own file), `GET /api/destination/fields` (a field-list destination's list, 409 for
      ones made from an example), `POST /api/destination/delete` (saved lists and in-memory ones only;
      examples are never overwritten or deleted from the app). Column ties are kept in memory per
      destination (`App.ties`), also for a list saved right after building it from an upload.
- [x] Page renamed **"Formatos de destino"** (nav on every page): cards of every format (format badge,
      fields, where it comes from), the chosen one's fields, "Usar para traducir →", "Editar campos"
      and "Eliminar" when it is a field list; "+ Crear formato" (name, JSON/CSV/Excel/XML, start
      from the fields of a synthetic example or your own file, editor) and "Subir un ejemplo…".
- [x] "Traducir datos": synthetic examples in one styled, grouped dropdown (Hospitales del reto /
      Otros ejemplos / Datos difíciles) instead of 11 buttons; "Guardar formato" under the field
      editor. The field editor is shared (`web/js/campos.js`).
- [x] Fixed: `[hidden]` lost to an old `.campo-form input { display: block }` rule; now always wins.
- [x] Tests: 9 more in `tests/test_field_list.py` (save, CLI load, ties, edit, rename, delete,
      examples protected, plain names). **243 tests pass.** Browser check: create from an example's
      fields, edit + rename, translate with it, save from "Traducir datos", delete; test files and
      recipes removed.
- [ ] Not done: editing a format made from an example in the page (it changes by changing the
      example); duplicating one as a field list.

### Phases 7 + 8: the two first translations, done together — done 2026-10-24
Asked by the user ("perform the next stage implementation (7 and 8) as they can be compacted into one").
Both run through the same pipeline and review screen; nothing in the core is per format or per
domain (`tests/test_generic.py` still greps it). Measured by `scripts/translations.py` →
`docs/TRANSLATIONS.md`.

**A. messy Excel → FHIR (clinical pack)**
- [x] Destination `expected/paciente_resumen_fhir.example.json` + rules: a synthetic Bundle with Patient,
      weight and height Observations (LOINC 29463-7 / 8302-2, UCUM kg / cm, vital-signs category),
      AllergyIntolerance and Condition. Allergies and diagnoses are list targets (`"multiple": "list"`).
- [x] **One row → a Patient + linked resources, with variable fan-out:** the FHIR writer writes a
      resource once per value when a one-value slot gets a list (`Condition.code.text` ← "DM2…",
      "HTA", "DLP" → three Conditions), each with its own `urn:uuid` and its reference to the Patient.
      A list element whose data is all empty goes with its fixed leaves (no more
      `telecom: [{"system": "phone"}]` without a number — a phase 6 bug).
- [x] **Full-name columns are split** (the phase 4 leftover): engine transform `name_part`
      (`{"part": "given" | "family", "surnames": 2}`; particles stay with their surname: "Ana de la
      Fuente Gil" → "Ana" / "de la Fuente Gil"). A pack hook `part_of` lets one column feed every one
      of its parts; the clinical pack uses it for "Nombre completo" / "Nombre y apellidos". Mapped with
      an issue ("revisar nombres compuestos"). The AI proposer's cross-check still marks such a column
      pending (not re-measured: needs Ollama).
- [x] **Several values:** a list target takes the values of every `from` column in order (no
      `join_columns`), and `split_values` (`{"sep": ";"}`) splits "HTA; DLP". The clinical pack proposes
      "Diagnóstico principal" + "Otros diagnósticos" together for a list of diagnoses.
- [x] Fixed on the way: a column of recognised diagnoses whose description says "texto libre del
      médico" was taken as the doctor's (role practitioner); a column of the pack's terms now belongs to
      the record's subject. Synonyms "diagnosticos", "diagnoses", "conditions", "juicio clinico".
- [x] Custom columns: hospital C's triage level carried as an `extension`, the unnamed column K
      dropped on record; h5's blood group carried, DNI dropped. Every non-empty source column has a
      recorded decision (test).
- [x] Golden: `tests/golden/fhir/<file>.plan.json` (reviewed plan + carry/drop) and
      `<file>.bundle.json` (byte for byte) for `hospital_c_messy.xlsx` and `hard/h5_excel_dificil.xlsx`,
      built by `tests/golden/build_golden.py` and reviewed patient by patient. The checker passes.
- [x] Hard data: h5's two "gap" fields (the name split) are now real answers; h5 is 15/0/0.
- [x] Reviewed end to end in the web app (6/6, one extra, one drop; "Diagnósticos" label added).
- [ ] Not done: diagnosis text → ICD-10 coding. Diagnoses go as `code.text` only, so nothing clinical
      is changed (C10); a coding transform must keep the text next to the code and be approved.
- [x] FHIR `given` gets "Lucía María" as one element, not two. **Decided by the user (2026-10-24):
      it stays one element.** Don't split given names.
- [x] qwen3:8b measured 2026-10-24 (`scripts/translations.py rules qwen3:8b`). First run: hospital C
      9/12 with **1 wrong** (`Condition.code.text` from "Diagnóstico principal" only), h5 10/12; the name
      split always pending. Then, at the user's request, **the AI path uses the same structure as the
      rules** (`proposer._fields_from_answer`): a full-name column feeds both parts (`part_of`; the
      clinical `conflict` no longer flags it; if the model picks another column, the split column is
      offered as pending), and a list target takes every column the rules found. The clinical system
      prompt now says a full-name column may go to both targets. Re-measured: hospital C **10/12, 2
      pending, 0 wrong**; h5 **11/12, 1 pending, 0 wrong** (`given` stays pending with the right column:
      the model doubts the split). The 3-hospital eval (`docs/EVAL.md`) with qwen3:8b after the prompt
      change: 15/15, 15/15, 15/15 (no regression; 30b not re-run).
**B. CSV → nested JSON and XML (no pack)**
- [x] Synthetic orders dataset `examples/pedidos/` (`build_pedidos.py` → `pedidos_lineas.csv` +
      `answers.json`): a wholesaler's order lines with a title line, odd headers ("Num. pedido",
      "Ref.", "% Dto."), three date shapes, decimal commas, an empty line, a total line, two custom
      columns and one line without an order number. Answers to the phase 8 open question: **both** XML
      and JSON, domain **orders**.
- [x] Destinations `examples/destinos/pedido_json.example.json` and `pedido_xml.example.xml` (order
      number as an attribute, `cliente` and `entrega` objects, repeated `linea`), each with
      `$group_by` on the order number: 7 rows → 3 orders, the line with no number set aside with its
      reason.
- [x] **Matching with no vocabulary, word by word** (`matcher.name_match`): the target's name and the
      names it sits under ("NIF cliente" → `cliente.nif`, "Ciudad entrega" → `entrega.ciudad`), cut words
      ("Num." → número, "Ref." → referencia), joined words ("E-mail"). Guesses stay **pending** with the
      column already chosen: an abbreviation ("% Dto." → descuento_pct) or a column named after the
      object ("Cliente" → `cliente.nombre`). With no pack, a fair candidate (≥ 0.4) is pending instead
      of "no data", so data is never left out silently. Only for targets with no concept: the clinical
      destinations behave exactly as before (behaviour snapshot unchanged apart from the name split).
- [x] Measured: rules **9 right, 2 pending, 0 wrong** for both JSON and XML; qwen3:8b **11/11, 0
      wrong** for both (~22 s); reviewed output equal
      to the known answer; the XML reads back. Reviewed end to end in the web app ("Líneas de pedido"
      in the examples dropdown).
- [x] `tests/test_translations.py` (16 tests, including the CLI default destination). **263 tests pass.**
- **Done when:** met — both translations run through the same pipeline and review screen, pass their
  checkers, match the known output, and no source column disappears without a recorded decision.
  Left: ICD-10 coding (C10), nested groups deeper than one level. (qwen3:30b re-run: not needed yet.)

### Later (unordered)
- HL7 v2 writer + checker (the hardest standard to write correctly).
- More formats: YAML, Parquet, SQL tables, EDI.
- Connectors: databases, SFTP, HTTP APIs.
- Unstructured sources (PDF, scans, free text) via AI extraction, always reviewed.
- More domain packs (invoices, logistics, HR...), only when a use case asks for one.

### Phase 9: evaluation set and calibration — done 2026-10-24
Results in [CALIBRATION.md](CALIBRATION.md); `scripts/calibrate.py` rebuilds it.
- [x] A generator, `evalset/` (outside the package; seeded, deterministic): invented records → messy files
      with the correct output known per row.
      - **patients** → `cdss_paciente` (clinical pack) as CSV, Excel, JSON, XML, HL7 v2, FHIR
      - **order lines** → `pedido_json` (no pack) as CSV, Excel, JSON, XML
      - mess: header languages / cryptic codes, section prefixes, title lines, encodings, separators, date
        shapes, sex codes, units, decimal commas, capitals, split or combined names, lost leading zeros,
        missing fields, distractor columns
- [x] Grading by **output values**, not column names (`evalset/grade.py`): right / pending / missed /
      wrong, wrong split into *silent* (passes every destination rule) and *caught* (the engine sets the
      rows aside), plus an oracle (true columns + the rules' transforms).
- [x] **Fixed on the way** (found by the set, seeds 0–299; the measurement uses other seeds):
      - phones written `0034…` or `+34 600 11 22 33` got no conversion
      - `19850412` dates outside HL7 weren't read as dates (now `%Y%m%d` + a review note)
      - a section prefix decided the meaning ("Dirección / CP" → street): a synonym only in the section
        is now context, and a field only the section names is pending
      - English "Full name" wasn't split; "National ID", "Medical record number", "Postcode", "C.P.",
        a `FAM` (relative) phone
      - with no pack, a column naming another object of the destination ("Fecha entrega" for the order's
        `fecha` when there is an `entrega` object) is a guess, pending
      - first measurement 105 wrong in 300 files; after the fixes 3 silent in 1200
- [x] Calibrated per score band (fit on seeds 1000+, checked on held-out seeds 2000+, 600 files each):
      rules **0.60–0.70 → 96%, 0.70–0.80 → 96%, 0.80–1.00 → 99.9%** right when accepted; held-out ECE
      **0.2%** (12% reading the raw score as a probability: the rules are *under*-confident). Saved in
      `multibridge/calibration.json`; `multibridge/calibration.py` looks it up.
- [x] The web app shows it: next to each confidence, "en pruebas sintéticas, propuestas así acertaron N de
      cada 100" (never "100 de 100"), with the count and interval on hover. The raw score still orders the
      review; the recipe's `confidence_kind` is unchanged. API: `measured` per field and per ranking option.
- [x] `tests/test_evalset.py` (34 tests): deterministic files, truth columns exist, oracle ≥ 97%, grading
      semantics, Wilson interval, monotone fit, the shipped table is monotone, each matcher fix, and **no
      silent mistakes on 60 fresh files**. API test for `measured`. 298 tests pass.
- **Measured weaknesses** (now known, not fixed): with no pack, the rules leave ~31% of order fields as
  "no data" when headers are English or cryptic (safe, but incomplete: an orders pack or the AI would
  cover it). The 3 silent mistakes are value-only guesses at 0.67–0.73 (a 5-digit code read as a postal
  code); making those pending would also send HUCA's right Z-segment weight/height to review, so it was
  left to the calibrated rate (96% in that band).
- Left: measure qwen3:8b on the set (`scripts/calibrate.py rules qwen3:8b --cases 60`, needs Ollama, ~1 min
  per file); more mess kinds as real exports show them.

### Phase 10: deployment as a portfolio project (decided 2026-10-24)
The user: this is a **portfolio project, not for a hospital**, and nothing paid. So:
- [x] **CI** (GitHub Actions, `.github/workflows/tests.yml`): the whole suite on every push and pull
      request, on Ubuntu with Python 3.10 (the oldest `pyproject.toml` allows) and 3.13, and on Windows 3.13.
      No Ollama needed (fake model). Rehearsed locally: a clean copy without ignored files, fresh venv,
      `pip install -e ".[dev]"`, 298 passed. `.gitattributes` keeps test data byte-exact (git must not
      turn the CRLF / lone CR line breaks of the examples into LF). **First run on GitHub 2026-10-24:
      3/3 green, 1 min 5 s.** Then: actions bumped to checkout@v5 / setup-python@v6 (Node 24; v4/v5 warned
      about Node 20), Ubuntu pinned to 24.04 (`ubuntu-latest` moves to Ubuntu 26), badge in the README.
- [ ] **Live demo on GitHub Pages, no server:** the same `web/` with the Python running in the visitor's
      browser (Pyodide; the core is standard library + openpyxl). `api()` in `web/js` calls the API's
      functions in Pyodide instead of over HTTP; recipes and saved formats live in the browser; the
      synthetic examples are bundled. Rules only. Visitors' files never leave their computer.
- [ ] A second workflow that builds and publishes the Pages demo on every push to `main`.
- [ ] **AI:** the main way stays "clone + `multibridge serve` + Ollama". On Pages, an *experimental*
      "connect your own Ollama" (`OLLAMA_ORIGINS=https://<user>.github.io ollama serve`; the browser
      may ask for local-network permission); `ai/ollama.py` needs a `fetch` path under Pyodide.
- [ ] README as a landing page: demo link, local install for the AI, the measured numbers, a GIF.
- Not for now (a real organisation would need them): corporate login, propose/approve roles, encryption at
  rest, audit log (C14), compliance paperwork (C16–C19), Jev (D9).

## 7. Open questions for the user

- *Answered 2026-10-24:* the repo name stays `multibridge-mapper` (the user: "multibridge-mapper is
  the correct name"). Don't ask again.
- *Answered 2026-10-24:* FHIR `given` keeps a compound given name as one element. No qwen3:30b
  re-run for now.
- *Answered 2026-10-24:* Grupo 5 is OK with its UI living in this repo (D10). Phase 8's destination:
  any format (done as both JSON and XML, orders as the domain).
- FHIR extensions need a base URL for custom fields (the user asked what it is, 2026-10-24: a web address
  that names each extra field, e.g. `https://<organisation>/fhir/StructureDefinition/nivel-triaje`; it
  only has to be unique and stable, it needn't serve a page). Until an organisation is chosen the example
  one stays. Ask again at deployment (phase 10).
- *Answered 2026-10-24:* D13–D15 approved ("yes keep them"). C1 is in `CLAUDE.md` (the user added it).
  ICD-10 coding: the user doesn't know yet; diagnoses stay text only (safe default, C10).
- Add the C1 rule ("never put real patient data in this repo") to `CLAUDE.md`. That's the user's file.

## 8. Session log (newest first, append only)

- **2026-10-24 (phase 10 starts):** the user: a portfolio project, free hosting, GitHub Pages without AI,
  AI by cloning or by the visitor's own Ollama. Phase 10 rewritten accordingly. CI added
  (`.github/workflows/tests.yml`, 3 combinations) and `.gitattributes` for byte-exact test data; rehearsed
  on a clean copy: 298 passed. Nothing committed (the user's call).

- **2026-10-24 (phase 9):** D13–D15 approved. Phase 9 done: `evalset/` generator (patients in 6 formats,
  orders in 4), grading by output values, `scripts/calibrate.py` → `docs/CALIBRATION.md` +
  `multibridge/calibration.json`, measured rate shown in the web app. The set found six matcher problems
  (phones, compact dates, section prefixes, English full names, a few synonyms, other-object names);
  wrong fields went from 105 in 300 files to 3 silent in 1200. Rules calibration: 96% / 96% / 99.9% per
  band, held-out ECE 0.2%. 298 tests pass. qwen3:8b not measured on the set (Ollama not asked).

- **2026-10-24 (latest):** Roadmap review with the user. Ticked what was already done (phase 2 eval
  re-run with qwen3:8b, phase 3 grouped examples, phase 4 name split) and fixed the test count (263).
  User answers: the name stays `multibridge-mapper`; FHIR `given` stays one element; no qwen3:30b
  re-run yet. Still open: FHIR extension base URL, D13–D15, C1 in `CLAUDE.md` (the user doesn't know yet).

- **2026-10-24 (later):** Phases 7 and 8 together at the user's request. Excel → FHIR Bundle (name
  split, one Condition / AllergyIntolerance per value, triage carried as an extension) with golden
  Bundles; CSV order lines → nested JSON and XML with no pack (word-by-word name matching, 9 right /
  2 pending / 0 wrong). `docs/TRANSLATIONS.md`, 261 tests pass, both checked in the web app. Then, at
  the user's request, qwen3:8b measured (after a laptop shutdown, rerun): orders 11/11 with 0 wrong;
  Excel → FHIR 9–10/12 with 1 wrong (one diagnosis column of two) and the name split pending.
  Fixed by letting the AI path reuse the rules' structure (name split, list columns) plus a prompt
  line: Excel → FHIR now 10–11/12 with 0 wrong; 3-hospital eval 45/45. Also fixed a phase 7
  regression found while listing the commands: with two examples in `expected/` the CLI had no
  default destination (a traceback); it now takes the first by name, like the web app. 263 tests
  pass. Next: the user's pick — ICD-10 coding (C10), HL7 v2 writer, qwen3:30b re-run.

- **2026-10-24:** Phase 6c at the user's request: "Formatos de destino" page where formats are
  created, edited, renamed and deleted (saved as `expected/<name>.fields.json`); examples in one
  grouped dropdown; "Guardar formato" in "Traducir datos". 243 tests pass. The user's old server on
  port 8766 was gone by now. Next: phase 7.

- **2026-10-23 (night):** Phase 6b at the user's request: a destination can be just a format plus a
  field list ("recibir todos los campos del archivo", editable: rename, retype, leave out, add).
  JSON, CSV, Excel, XML; FHIR/HL7 still need an example. Fixed the HL7 sniff (`MSH-3` CSV header),
  list targets losing values, and the dropped-connection traceback. 234 tests pass. Next: phase 7.

- **2026-10-23:** Phase 6 done: destinations from an example in any format (JSON, CSV, Excel,
  XML, FHIR template), writers and checkers for all five, grouping (many rows → one item), list
  targets, custom fields carried or dropped on record, web app "De → A" with uploads and
  download in the destination's format. XML reader added. Fixed `/api/field` ignoring the pack.
  206 tests pass. Next: phase 7 (messy Excel → FHIR, golden + hard data).

- **2026-10-22 (late night, later):** Phase 5 done: generic core, format plug-ins (`formats/`),
  domain packs (`packs/`, clinical first), personal-data detection in every domain (C20),
  COMPLIANCE split (D15). Behaviour snapshot byte-identical on all 12 example files.
  179 tests pass. Next: phase 6 (destination from any example + writers).

- **2026-10-22 (late night):** **Direction changed** at the user's request: from a hospital mapper
  to a translator from any format to any format, any type of data (section 2a).
  - Approved: generic core with clinical as the first domain pack (D11); first translations messy
    Excel → FHIR and CSV → nested XML/JSON (D12). Proposed D13–D15.
  - New phases 5–8; old calibration and deployment phases renumbered to 9 and 10. Nothing built yet.

- **2026-10-22 (night):** Phase 3 done.
  - `multibridge serve` serves the copied hackathon site from `web/`, wired to `multibridge/api.py`.
  - Client branding removed; the server rebuilds provenance and the reuse signature on approval.
  - Verified in the browser. 171 tests pass.
  - Added a `multibridge-web` entry to the hackathon folder's `.claude/launch.json` (Claude preview
    config only, not the app).

- **2026-10-22 (later):** Selector columns: pick a repetition or row by its code (PID-3.5, OBX-3,
  FHIR Observation code). Hard set with rules: 73/75 right, 0 wrong mappings (left: MED on purpose,
  home vs mobile tie). 162 tests pass. Next: phase 3 web app.

- **2026-10-22:** Hard-data test without AI (phase 4).
  - The pipeline was already exact with correct recipes.
  - The rules proposer went from 4 wrong + several dangerous picks to 73/75 right and 0 dangerous.
  - Fixed the mixed-date bug; FHIR slicing by `use`; joined surnames; units from values;
    pending for ties, repeated identifiers, Observations and full names.
  - 159 tests pass. Next: the user wants to wire into the web app (phase 3).

- **2026-10-21 (night):** Recorded D10 and a new phase 3 at the user's request: reuse the
  hackathon website as the review UI via a local API, instead of Streamlit. Not started.

- **2026-10-21 (evening):**
  - Phase 2 mostly done: Ollama client, masked AI view, proposer with reply checks and rules
    cross-check, CLI `--model`.
  - First real evaluation: qwen3:8b 44/45 on the reviewed hospitals; it invents sources for fields
    that have none. Added checks and replay tests for every mistake seen. 134 tests pass.
  - Re-run pending: Ollama went offline mid-run.
- **2026-10-21 (later):** Phase 1 done. The user approved D2–D4. New pipeline: records → expected →
  recipe → engine; the old contract/driver modules are gone; 101 tests pass; golden output identical.
  Next: phase 2, the local Qwen proposer.
- **2026-10-21:** Ollama 0.40.6 installed with `qwen3:8b` and `qwen3:30b`; similar speed on this
  laptop (30b is mixture of experts). Decided thinking off by default, `keep_alive: 0`. Wrote this
  roadmap.
- **2026-10-19/20:**
  - Built the parsers, profile/privacy view and diagnosis normalizer.
  - Then the contract, rules matcher, driver approval, engine and the 3-hospital golden test (90 tests).
  - User feedback: parsers good; engine a confusing mix, too far from the hackathon idea; wants local AI.
  - Wrote `docs/JEV.md` (Jev = TypeSafe AI decision model, cloud-only) and `docs/COMPLIANCE.md`.
