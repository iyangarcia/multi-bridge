# JEV (TypeSafe AI): what it is and where it fits in Multi Bridge

*Researched 2026-10-19. Jev is in early access, so re-check before building against it.*

## What Jev is

**Jev** is a **"System One" decision model** from **TypeSafe AI**, launched 15 September 2026.
It is **not a chat model**: it doesn't write text. You give it a **state** (your data, as text or
JSON) and a set of **typed questions**. It returns **bounded answers with probabilities and
confidence**, evaluating all questions in parallel and independently against the same state.

| Question type | Asks | Returns |
|---|---|---|
| **Choice** | pick one option from a list you declare | `choice`, `probabilities`, `confidence` |
| **Score** | rate the state on a rubric | `score`, `probabilities`, `confidence` |
| **Noul** | is this statement true? | `noul` (a probability from 0 to 1) |

- Answers can only be the options you declared, so there's no JSON parsing and no hallucinated free text.
- Built for classification, routing, scoring, extraction, verification and guardrails.
  Not meant for chat, code or prose.
- Training method, as the vendor calls it: "Reinforcement Learning for Calibrated Decisions".
- Company: TypeSafe AI. CEO Diogo Almeida, ex-OpenAI (InstructGPT/RLHF). $40M seed led by DCVC.

## Practical facts

| | |
|---|---|
| Model ID | `jev-latest` alias (currently `jev-1.13.0`). On Cloudflare: `typesafe/jev` |
| Access | Early access via typesafe.ai and console.typesafe.ai. Also through Netlify AI Gateway and Cloudflare |
| SDK | TypeScript `@typesafe-ai/sdk` (Node 20+): `client.systemOne({ state, questions })` with `choice`/`score`/`noul` helpers. No public Python SDK found; call it over HTTP or through a gateway |
| Context | about **32k tokens** shared by state and questions (~150k characters) |
| Latency | 70–500 ms end to end (vendor-reported) |
| Price | about **$0.042 per million input tokens, output free** (vendor/secondary sources). Rate limits not published |
| Docs | https://docs.typesafe.ai/introduction · index: https://docs.typesafe.ai/llms.txt |

### Unknown (ask TypeSafe before using it with hospital data)
- **Data retention, GDPR, EU region, DPA:** not published.
- **Self-hosting / on-prem / VPC:** not published. The service is serverless. **Assume Jev
  cannot run inside the hospital.**
- Independent accuracy and calibration benchmarks: none at launch. All speed and cost figures are vendor claims.

## How Jev fits Multi Bridge

Jev's primitives line up almost exactly with the decisions the mapper has to make:

| Mapper decision (design doc section) | Jev question |
|---|---|
| Which EXPECTED field does this source field go to? (§7) | **Choice** over the target fields + "none" |
| Relation type: equivalent / partial / broader / narrower / incompatible / insufficient (§7) | **Choice** over those 6 |
| Is this proposed pair correct? (§8) | **Noul**: its probability feeds the confidence traffic light |
| `IRA` in this column: renal or respiratory? | **Choice** with the column's context (service, other values) as state |
| How confident is this mapping? (§8) | **Score** / `confidence` (still calibrate it on our own labelled set) |
| Which field kind is this: identifier, diagnosis, measure...? | **Choice** |

### The privacy rule
Jev is cloud-only, so it only ever receives **`profile.as_ai()`**: structure, types, units and
non-identifying categories. **Never the values of sensitive fields.** The hospital must authorise
any remote model (design doc §1.1). If it doesn't, Jev is simply not used.

### Who does what

| Situation | Handled by |
|---|---|
| Standard fields (`PID-5.1`, `Patient.birthDate`) | built-in rules, no AI |
| Known diagnoses, abbreviations, typos | `terms.LexicalNormalizer` |
| Structure mapping onto EXPECTED, relation types, ambiguity calls on metadata | **Jev** (if authorised) |
| **Custom fields and unusual placements** (Z-segments, FHIR extensions, unnamed columns, DNI in PID-19), where real sample values are needed | **local open-weight model** (Ollama with Qwen 2.5 / Llama 3.1 / Mistral, 7–14B) inside the hospital |
| Anything still unresolved | a human |

AI only runs **once per new source layout**, when the mapping is designed. Once a human approves
the mapping, the driver engine applies it with no AI calls per record.

### Design decision: copy Jev's interface
The internal "decider" interface copies Jev's primitives: `choice`, `score` and `noul`, each over a
state, returning probabilities and confidence. Backends:

- `rules`: offline, deterministic (default)
- `local`: Ollama model forced to answer only from the declared options; may see sample values
- `jev`: TypeSafe API; only receives `as_ai()`

The matcher then never knows which backend answered, and a hospital without internet or without
cloud authorisation still works. Code will live next to `multibridge/terms/` (the `Normalizer`
interface is the first instance of this pattern).

## Sources
- TypeSafe AI site and docs: https://typesafe.ai · https://docs.typesafe.ai/introduction
- Netlify AI Gateway changelog: https://www.netlify.com/changelog/typesafe-jev-ai-gateway/
- Let's Data Science, launch coverage: https://letsdatascience.com/news/typesafe-ai-launches-jev-decision-model-889a38c0
- Pricing write-up (eesel): https://www.eesel.ai/blog/typesafe-jev-pricing
- VKTR, launch coverage: https://www.vktr.com/ai-platforms/chatgpt-cocreator-launches-typesafe-ai-with-jev/
