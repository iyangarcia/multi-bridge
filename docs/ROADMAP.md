# Roadmap and handoff

*The single place that says where the project is, what was decided, and what to do next.
Written so that someone (or an AI session) with no memory of earlier conversations can continue.
Last updated: 2026-10-21, phase 2 in progress.*

## 0. Read this first (new session checklist)

1. Read this file, then [COMPLIANCE.md](COMPLIANCE.md) (legal constraints C1–C19), then
   [JEV.md](JEV.md) (what "JEV" means), then the [README](../README.md).
2. Run the tests: `.venv/Scripts/python -m pytest -q`. They must pass before and after your changes.
3. Find the first unchecked task in section 6 and continue from there. Update the checkboxes and
   the session log (section 8) as you go.

## 1. Hard rules (non-negotiable)

- **No git.** Never commit, push or run git commands, and don't suggest it. The user manages GitHub
  (`CLAUDE.md`).
- **The hackathon folder is read-only reference:** `C:\Users\Usuario\Desktop\TalentUO 2026 Grupo 5`
  (original web app in `app/`, design docs `Mapeador_universal_IA.docx` and
  `Documentación mapeador.docx`). Don't modify it.
- **Synthetic data only** (C1). Never read, request or create real patient data.
- **The AI is local** (C3): Ollama on `127.0.0.1:11434` only. No cloud model receives data. Jev
  only later, with structure only, and only if a hospital authorises it (C5).
- **A human approves every mapping** before it runs (C8). No score or model output skips approval.
- **Scores are labelled honestly.** Rule scores and model confidences are *uncalibrated* until
  phase 5. Never present them as probabilities.
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

## 3. Environment

| | |
|---|---|
| Machine | Windows 11, i7-14650HX, 32 GB RAM, RTX 4060 Laptop **8 GB VRAM** |
| Python | 3.13, venv in `.venv/` (`.venv/Scripts/python`, `.venv/Scripts/multibridge`) |
| Dependencies | `openpyxl`; dev: `pytest`. Prefer the standard library (for example `urllib` for Ollama) over new packages |
| Ollama | 0.40.6, running on `127.0.0.1:11434`, `OLLAMA_HOST` unset (keep it that way) |
| Models | `qwen3:8b` (5.2 GB, fits entirely on the GPU) and `qwen3:30b` (18 GB, mixture of experts with ~3B active parameters, split GPU+RAM). On this laptop both run at similar speed |

## 4. Current state (2026-10-21, after phase 1)

101 tests pass. The pipeline follows the hackathon design:

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
- [ ] **Re-run `scripts/eval_proposer.py rules qwen3:8b qwen3:30b` with the checks in place.** The
      second run stopped after the rules rows because Ollama went offline (connection refused; an
      Ollama update was pending). Needs Ollama running: running `ollama ps` starts it. Ask the user
      before starting it. The script now saves after every file and records model errors as rows.
- [ ] Record the model digest (exact version) in recipes (C9, C15).
- **Done when:** the re-run shows no *wrong* fields for qwen3:8b on the 3 reviewed hospitals
  (pending is acceptable), and `EVAL.md` documents every difference.

### Phase 3: review UI (Streamlit, as in the hackathon MVP)
- [ ] Upload the example output + source file. A table of target ↔ source with a traffic light,
      dropdowns to change the source or transform, the unmatched lists, and Approve disabled while
      anything is pending. Download the output.
- [ ] A "What the AI sees" vs "Your data" panel (the pitch moment). Synthetic data only in demos.

### Phase 4: harder data
- [ ] Code-filtered sources: HL7 `OBX-5` and FHIR `Observation.value` selected by `OBX-3`/`code`
      (LOINC 29463-7 = weight, 8302-2 = height). Today these are marked pending.
- [ ] Split column: "Nombre y apellidos" → given + family, with human review (Spanish names are hard).
- [ ] Terminology transform: diagnosis text → ICD-10 via `terms/`, keeping the original text next
      to the code; every change approved (C10).
- [ ] Make the messy Excel (`examples/hospital_c_messy.xlsx`) a 4th golden case.

### Phase 5: evaluation set and calibration
- [ ] A generator: synthetic patients → messy CSV/Excel/HL7/FHIR with known correct mappings.
- [ ] Calibrate confidences per score band, so that "0.9" means right about 9 in 10. Only then
      may the UI call it a probability.

### Phase 6: deployment and compliance
- [ ] FastAPI service + Docker image (on-prem or private cloud), corporate login, roles, encryption
      at rest, audit log (C14).
- [ ] Compliance paperwork the hospital will ask for: C16–C19.
- [ ] Jev backend (D9) only after TypeSafe answers the questions in `JEV.md` and a hospital authorises it.

## 7. Open questions for the user

- Is the Excel template as EXPECTED needed in phase 1, or is JSON enough at first?
- Add the C1 rule ("never put real patient data in this repo") to `CLAUDE.md`. That's the user's file.

## 8. Session log (newest first, append only)

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
