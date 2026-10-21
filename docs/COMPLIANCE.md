# Legal and data-protection constraints

*Written 2026-10-19. This is an engineering checklist, **not legal advice**. Before any use with
real patient data, the hospital's Data Protection Officer (DPD/DPO) and a lawyer must review it,
and the hospital must run its own impact assessment (see C11).*

Every constraint below is numbered, says **why** (the law), **what the code must do**, and its
**status**: ✅ done · 🟡 partial · ❌ to do. New features must not break a ✅ item.

---

## 1. Who is who

| Role | Who | Consequence |
|---|---|---|
| **Controller** (*responsable del tratamiento*) | the hospital | decides the purpose; runs the DPIA; answers to patients and to the AEPD |
| **Processor** (*encargado del tratamiento*) | whoever installs and operates Multi Bridge for the hospital (e.g. Pragmatech) | needs a written contract under GDPR art. 28; only acts on the hospital's instructions |
| **Sub-processor** | any external service that would receive data (e.g. Jev in the cloud) | needs the hospital's **prior written authorisation** (art. 28.2) and a contract with the same guarantees |
| **Development tools** | Claude Code and any other cloud AI used to *build* the project | must **never** receive real data (C1) |

## 2. The data

- Clinical data (diagnoses, allergies, blood group, weight) is **health data**, a *special
  category* (GDPR art. 4.15 and art. 9). Processing it is forbidden unless an art. 9.2 exception
  applies. For healthcare delivery that is art. 9.2.h, together with LOPDGDD art. 9.
- Names, DNI/NIE, NHC/MRN, phones, addresses and birth dates are **identifiers**.
- **Pseudonymised data is still personal data** (GDPR art. 4.5, recital 26). Replacing names
  with fake ones does not make the data anonymous: rare combinations (age 97 + small village +
  rare disease) can re-identify people. Only truly anonymised data falls outside the GDPR, and
  the AEPD sets a high bar for that.

## 3. Laws that apply

| Law | Why it matters here |
|---|---|
| **GDPR** (Regulation (EU) 2016/679) | the base framework: principles (art. 5), health data (art. 9), privacy by design (art. 25), processors (art. 28), records (art. 30), security (art. 32), breaches (art. 33–34), DPIA (art. 35), transfers outside the EU (art. 44–49) |
| **LOPDGDD** (Ley Orgánica 3/2018) | Spain's GDPR law: health data rules (art. 9), additional provision 17 on health data, the DPO obligation for healthcare centres (art. 34) |
| **Ley 41/2002** (patient autonomy) | confidentiality of clinical information; the clinical record (*historia clínica*) is the hospital's, kept for at least 5 years after each discharge. Multi Bridge must not become a second, uncontrolled copy of it |
| **ENS** (Real Decreto 311/2022) | public hospitals must require *Esquema Nacional de Seguridad* compliance from their technology providers. Health systems are typically category MEDIA or ALTA |
| **NIS2** (Directive (EU) 2022/2555) | hospitals are in scope (health sector) and must manage supply-chain security, which includes us. *Spain had not passed its transposition law as of Oct 2026*: check the BOE |
| **EU AI Act** (Regulation (EU) 2024/1689) | AI literacy for staff using AI systems (art. 4, applies since Feb 2025). The mapping assistant is probably **not high-risk** (not in Annex III, makes no decisions about patients), but document why (C18). *A "Digital Omnibus" amendment to delay high-risk deadlines was provisionally agreed in 2026; check whether it has been formally adopted* |
| **Medical Device Regulation** (Regulation (EU) 2017/745) + guidance MDCG 2019-11 | software that only stores, transfers or converts data is generally **not** a medical device. **Risk:** turning free-text diagnoses into ICD-10 codes changes clinical information that feeds a CDSS (which may be a device). Keep terminology changes human-approved, and agree with Pragmatech's regulatory lead how Multi Bridge appears in the CDSS technical file |
| **EHDS** (Regulation (EU) 2025/327) | future EU rules for electronic health record systems and interoperability, phased in from 2027 onward. An opportunity: aligning with FHIR now fits where the EU is heading |

---

## 4. Constraints

### Where data may go

**C1. Development uses synthetic data only.** ✅ / ❌
- Real patient data never goes into this repo, tests, issues, screenshots, or any chat with a
  cloud AI, including Claude Code. Anything sent to those tools leaves the hospital.
- ✅ Everything in `examples/` is synthetic.
- ❌ Add this rule to the repo's `CLAUDE.md`, so every AI session sees it.

**C2. Real data is processed only inside the hospital's environment** (its data centre, or a
private cloud the hospital controls). Design doc §1.1.
- ✅ Parsers and engine make no network calls.
- ❌ Add a test that fails if any module in `parsers/`, `profile.py` or `engine.py` imports
  networking libraries.

**C3. The AI is local by default.**
- The model runs on the same machine (Ollama), listening only on `127.0.0.1`, never on
  `0.0.0.0`. Remote models are **off** unless a config flag is set *and* the hospital has
  authorised them in writing (C5).
- ✅ `ai/ollama.py` refuses any host that isn't `127.0.0.1` / `localhost` / `::1`, even if
  `MULTIBRIDGE_OLLAMA_URL` is changed (test: `test_ollama_must_be_local`). No remote backend exists.
- ✅ The model is unloaded from memory when the proposal is done (`keep_alive: 0`).

### What the AI may see

**C4. Data minimisation** (GDPR art. 5.1.c and art. 25). The AI gets the least it needs to propose a
mapping, in three levels:
1. **structure:** names, descriptions, types ✅ (`as_ai(level="structure")`)
2. **profile:** plus formats, units, null ratio, and *non-identifying* categories (`H/M`, `A+`) ✅ (`as_ai(level="profile")`)
3. **masked samples** ✅ (`aiview.py`, what the local proposer actually sends): every value keeps its
   *shape* but loses its content: `FERNANDEZ ALVAREZ` → `XXXXXXXXX XXXXXXX`, `HC-7781` → `XX-9999`.
   Non-sensitive measurements are sent as min / median / max only. The destination example's
   values are masked too, since an example file could hold a real record.
   - *Changed from the first plan:* instead of fake values (fake DNI, names from a list), samples are
     masked. That's simpler and can't leak content; the only thing it reveals is length.

Free text (diagnoses, notes) is sent as a **terminology summary** ("4 of 5 values recognised as
ICD-10"), never the raw text, which can contain names. ✅

**C5. If a remote AI (e.g. Jev) is ever used.** ❌ Jev's terms are unknown (`docs/JEV.md`).
- Only levels 1–2, never values, even pseudonymised ones.
- Required before enabling:
  - hospital's written authorisation (art. 28.2)
  - a processing contract with the provider
  - no training on our inputs, and zero or minimal retention
  - EU data location, or a valid transfer mechanism for the US (EU–US Data Privacy Framework or Standard Contractual Clauses; art. 44–49)
  - an entry in the DPIA

**C6. Default deny for unknown columns.** ✅ for the proposer (`aiview.cleared()`)
- Real values reach the model only if the column is *positively* cleared: a non-sensitive category
  list of at most 12 short values (`H/M`, `A+/0-`, `I/E`). Everything else is masked or summarised.
- Tests: `test_prompt_never_contains_values_of_uncleared_columns` and
  `test_sensitive_columns_are_never_cleared`, over all six example files.
- 🟡 The older `profile.as_ai()` (used by `multibridge inspect --as-ai`) still works the other way
  round, withholding only *detected* sensitive columns. It sends nothing anywhere, but should be
  switched to `aiview` for consistency.

**C7. Instructions hidden in data (prompt injection).** ✅ / 🟡
- ✅ Free-text values never reach the prompt (they are masked), so text written in a hospital
  file can't act as an instruction. Only cleared category values and column names/descriptions do.
- ✅ The reply is constrained by a JSON schema whose enums are the real targets and columns, and
  then checked again (`proposer._fields_from_answer`): invented columns are dropped, a column can't
  feed two fields, required fields can't be "no_data", translations must land on allowed values.
  Anything dubious becomes *pending*.
- ✅ Every result goes through human review (C8).
- 🟡 Column names and descriptions do come from the file (a Z-segment description, an Excel
  comment). They could carry injected text. The schema and review limit what that can achieve.

### Decisions and traceability

**C8. A human approves every mapping before it runs.** ✅ `recipe.py`
- Approval records who, when, and a hash of the exact plan. Any change invalidates it.

**C9. Traceability: what the AI proposed vs what the human changed** (design doc §5 "Trazabilidad"; AI Act transparency). ✅ / 🟡
- ✅ Each recipe field keeps `proposed_by` (`rules`, `qwen3:8b`, or `qwen3:8b (think)` for the
  second pass), a frozen copy of the original `proposal`, and `changed_by` when the approver's
  decision differs from it.
- 🟡 The model *version* (Ollama digest) isn't recorded yet, only its name (see C15).

**C10. No silent clinical changes.** ✅ / ❌
- ✅ Ambiguous or unknown terms (`IRA`, `DiabA`) are never auto-resolved (`terms/`).
- ❌ When a terminology transform exists, a text → code change must be approved like any other
  mapping, and the output must keep the original text next to the code.

### Outputs, logs and storage

**C11. Outputs contain personal data.**
- ✅ `out/` is git-ignored.
- ✅ Run reports contain no values, only record positions and reasons.
- 🟡 `multibridge inspect` prints sample values to the terminal. Fine on the hospital's machine,
  but never paste that output into tickets or chats. ❌ Add a `--no-values` flag.

**C12. Recipes contain no personal data.**
- Recipes hold structure, column descriptions and harmless category translations (`0+ → O+`), so
  they can be shared with other hospitals. Approved recipes are also fed back to the model as
  worked examples. ❌ Add a test that scans saved recipes for values of sensitive fields.

**C13. Multi Bridge is a pass-through, not a store.** ❌
- It must not keep copies of clinical data beyond what one delivery needs. Retention of the
  clinical record is the hospital's job (Ley 41/2002), not ours.
- Configurable automatic deletion of `out/` after delivery.

### Security (GDPR art. 32 + ENS)

**C14. Deployment security.** ❌ Comes with the API and Docker step.
- Corporate login (SSO) and roles: who can propose, who can approve.
- Encryption at rest for outputs and recipes.
- TLS on any internal connection.
- Audit log of runs and approvals.
- Backups under the hospital's policy.
- Dependencies pinned and scanned.

**C15. Model provenance.** 🟡
- Model weights come only from official sources, with a licence that allows this use. Check
  each model's licence: most Qwen3 sizes are Apache 2.0, but some older Qwen sizes use a custom
  licence. In use: `qwen3:8b` and `qwen3:30b` from the Ollama library.
- ✅ The model name is recorded per field (C9). ❌ Record the exact version (the Ollama model
  digest) too, so a recipe says precisely which weights proposed it.

### Paperwork the hospital will ask for

**C16. DPIA (EIPD) before go-live** (art. 35): mandatory for large-scale processing of health data.
❌ The hospital runs it. We supply this document, the data-flow diagram below, and the security
measures.

**C17. Records of processing** (art. 30.2), kept by the processor. ❌

**C18. AI Act documentation.** ❌ A short statement covering:
- the intended purpose ("assist a human in designing data mappings; makes no decisions about patients")
- why it isn't high-risk
- AI-literacy guidance for the people who review mappings

**C19. Breach process.** ❌ A written procedure: notify the hospital "without undue delay"
(art. 33.2), so the hospital can notify the AEPD within 72 hours.

---

## 5. Data flow (target design)

```
 inside the hospital ──────────────────────────────────────────────────────────────
 │                                                                                 │
 │  hospital file ─► parsers ─► profile ─► as_ai(level 1–3) ─► local Qwen          │
 │   (real data)                 │          structure, categories, fake samples    │
 │                               │                                │                │
 │                               │                      proposed mapping (JSON)    │
 │                               ▼                                ▼                │
 │                         engine ◄── approved recipe ◄── human review + approval  │
 │                               │       (no personal data)                        │
 │                               ▼                                                 │
 │                     clinical app (CDSS)   out/ (deleted after delivery)         │
 ───────────────────────────────────────────────────────────────────────────────────
   outside (only with written authorisation, C5): Jev ◄── as_ai level 1–2 only
   never: real data to Claude Code / any cloud AI used for development (C1)
```

## 6. Open questions

- **Jev:** data retention, GDPR terms, EU hosting: unknown. Ask TypeSafe before any use (C5).
- **MDR:** does turning diagnosis text into codes make Multi Bridge part of the CDSS as a medical
  device? Decide with Pragmatech's regulatory lead.
- **ENS category** for the deployment: decided by the hospital.
- **NIS2:** check whether Spain's transposition law has been passed.
- **AI Act:** check whether the Digital Omnibus amendment was formally adopted, and its final dates.

## Sources

- GDPR: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- LOPDGDD (LO 3/2018): https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673
- Ley 41/2002 (patient autonomy): https://www.boe.es/buscar/act.php?id=BOE-A-2002-22188
- ENS (RD 311/2022): https://www.boe.es/buscar/act.php?id=BOE-A-2022-7191
- AI Act (Regulation (EU) 2024/1689): https://eur-lex.europa.eu/eli/reg/2024/1689/oj
- Medical Device Regulation (EU) 2017/745: https://eur-lex.europa.eu/eli/reg/2017/745/oj
- EHDS (Regulation (EU) 2025/327): https://eur-lex.europa.eu/eli/reg/2025/327/oj
- AEPD (Spanish data protection authority), guidance on anonymisation and DPIAs: https://www.aepd.es
- AI Act delay, provisional agreement (June 2026): https://datamatters.sidley.com/2026/06/22/eu-lawmakers-reach-provisional-agreement-to-delay-key-eu-ai-act-obligations/
- NIS2 in Spain, draft law status: https://www.cuatrecasas.com/es/spain/propiedad-intelectual/art/aprobado-anteproyecto-ley-transpone-la-directiva-nis2
