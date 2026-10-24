# How Multi Bridge works inside

This page follows one file through the application, from upload to output. It explains how each
destination field gets its source, its transforms and its status, and why the result may be
"mapped", "pending" or "no data". Every number and message on this page comes from running the
code on the synthetic files in `examples/`.

- [The pipeline in one picture](#the-pipeline-in-one-picture)
- [1. Reading: every format becomes the same fields](#1-reading-every-format-becomes-the-same-fields)
- [2. Profiling: what each column looks like](#2-profiling-what-each-column-looks-like)
- [3. One flat row per record](#3-one-flat-row-per-record)
- [4. The destination: what it wants](#4-the-destination-what-it-wants)
- [5. Deciding: who decides what](#5-deciding-who-decides-what)
- [6. The rules proposer, step by step](#6-the-rules-proposer-step-by-step)
- [7. Worked examples: real decisions](#7-worked-examples-real-decisions)
- [8. The AI proposer](#8-the-ai-proposer)
- [9. Confidence: what the number means](#9-confidence-what-the-number-means)
- [10. Review, approval and reuse](#10-review-approval-and-reuse)
- [11. The engine](#11-the-engine)
- [Design decisions](#design-decisions)
- [Where to change things](#where-to-change-things)

## The pipeline in one picture

```
 source file ──► 1 read ──► 2 profile ──► 3 flat rows ──┐
 (CSV, Excel, JSON, XML,  formats/     profile.py    records.py │
  HL7 v2, FHIR)           parsers/                   selectors.py
                                                                ├──► 5 propose ──► 6 human review ──► recipe ──► 7 engine ──► output file
 destination ──────────► 4 targets ─────────────────────────────┘    matcher.py     web app / CLI     recipe.py   engine.py   formats/ writer
 (an example of the       expected.py                                proposer.py                                               + checker
  output, or a field list)
```

The order matters for one reason: **everything after step 3 is the same for every format.** The
proposer, the review and the engine only see named columns with values, like a spreadsheet.
That is how one destination serves an HL7 feed, a FHIR API and a hand-made Excel file with no code
per pair of formats.

## 1. Reading: every format becomes the same fields

Each format has a plug-in in `multibridge/formats/`. It reads the file into a `Dataset`: a list of
`Field`s (`multibridge/model.py`), each with a path, a label, an entity (table, segment or
resource), a description if the format has one, and its values.

| Format | Path of a field | Where its description comes from |
|---|---|---|
| HL7 v2 | `PID-5.2`, `ZPA-3` | the standard's field names; `Z` segments are marked `custom` |
| FHIR | `Patient.birthDate`, `Observation.valueQuantity.value` | the resource and element names; extensions are marked `custom` |
| CSV / Excel | the header: `Paciente / F. Nac.` | merged group headers become a prefix, cell comments become descriptions |
| JSON / XML | `cliente.nif`, `pedido/@numero` | the nesting |

Excel files made by people get extra work in `parsers/table.py`. It skips title rows and footers,
finds the real table when a sheet has two, joins merged group headers into labels such as
`Antropometría / Peso (kg)`, and reads cell comments as documentation.

## 2. Profiling: what each column looks like

`profile.py` looks at the values of each field and fills in:

- **Type and format.** For example `date` with `dd/mm/yyyy`, `decimal` with `decimal comma`, a
  `string` with `leading zeros`, or a column that mixes date shapes (`mixed`). A number such as
  `03001` stays text, because turning it into a number would lose the zero.
- **Unit.** It comes from the label (`Peso (kg)`, `Talla_cm`) or from the format (`OBX-6`, FHIR
  `valueQuantity.unit`).
- **Kind.** A column can be categorical, free text or numeric, or it can hold terms of a domain
  pack (diagnoses, for the clinical pack).
- **Personal data.** Names, ID documents, contact details, addresses and dates of birth are
  detected in every domain. Each installed pack adds its own hints, such as the medical record
  number. Profiling runs before the destination is known, so it uses every pack's detectors: it is
  safer to flag too much than to miss something.

These facts drive two things later on: the transforms (step 6) and what the AI is allowed to see
(step 8).

## 3. One flat row per record

`records.py` turns the dataset into **one row per record**. The format plug-in decides what one
record is:

- **HL7 v2:** one message, with all its segments side by side.
- **FHIR:** a Patient with the resources that point to it.
- **CSV / Excel:** one data row of the main table.

When a linked record repeats (two allergies, two identifiers), the cell holds a list.

**Selector columns** handle structures that repeat and say what each copy is with a code
(`selectors.py`). Weight and height both live in `OBX-5`, and only `OBX-3` says which is which.
So the reader adds columns that pick one copy by its code:

```
OBX-5 [OBX-3.1=29463-7]        the OBX-5 of the segment whose code is LOINC 29463-7 (body weight)
PID-3.1 [PID-3.5=MR]           the identifier whose type is MR (medical record number)
```

From then on they are ordinary columns: the proposer scores them and a recipe can name them.

## 4. The destination: what it wants

A destination is **an example of the output in its own format** (`expected/*.example.json`, or a
CSV, Excel, XML or FHIR file), or just a format with a list of fields. `expected.py` turns it into
`Target`s, each with:

- a path (`paciente.fecha_nacimiento`, `lineas[].cantidad`) and a type taken from the example value;
- the example itself, kept as a template, so the output looks the same: same nesting, same date
  style, same fixed values;
- a **concept**, the meaning the destination's pack gives to the name. The last part of the path
  decides, so `direccion.ciudad` is a city, not a street. With no pack there are no concepts.

An optional `<name>.rules.json` adds what an example can't show: `required`, allowed values
(`enum`), a `pattern`, a `range`, a `unit`, `case: "title"`, how to handle several values
(`multiple`), the pack (`"$pack": "clinical"`) and grouping (`"$group_by": "numero"`).

## 5. Deciding: who decides what

A proposal gives each target four things:

| | Example | Decided by |
|---|---|---|
| **from** | `PID-7`, or `PV1-7.3` + `PV1-7.2` | the AI model, or the rules if there is no model |
| **transforms** | `date %Y%m%d → ISO`, `translate F→female` | always the code, from the profile |
| **status** | `mapped`, `pending` or `no_data` | the proposer, then checks that can only make it stricter |
| **confidence + why + issues** | `0.94`, "posición estándar (PID-7)" | the proposer |

Picking columns needs judgement, so the model is good at it. Formats need exactness: the profile
already knows a column is `dd/mm/yyyy`, so the code writes the transform instead of trusting a
model to spell `%d/%m/%Y`.

The three statuses:

- **mapped:** a source was found, and nothing about it needs a human.
- **pending:** a human must decide before approval. Either a source might be right but something
  is doubtful, or a required field has no source. Nothing pending can be approved.
- **no_data:** no column is good enough, and the field isn't required. The output leaves it empty.

## 6. The rules proposer, step by step

`matcher.py` runs with no AI at all. It is what the GitHub Pages demo uses, the fallback when
Ollama is off, and a cross-check for the AI.

### 6.1 Evidence: what each column might mean

For every source column, `concepts.py` collects evidence for each concept of the destination's
pack, using four kinds:

| Kind | When | Weight | Example reason shown |
|---|---|---|---|
| **standard** | the field sits where a standard puts that concept | 1.0 | `posición estándar (PID-7)` |
| **name** | a synonym appears in the label, the path or the specific part of the description | 1.0 | `el nombre contiene «f nac»` |
| **context** | a synonym appears only in the section (`Dirección / POBL`) or the general description | 0.5 | `la sección contiene «direccion»` |
| **values** | the values look like it (the pack's value detectors) | 0.35–0.9 | `los valores son grupos sanguíneos (A+, 0-...)` |

Value detectors only see shapes and ranges. Blood groups match `A+`, `0-` or `AB RH POS`. DNI/NIE
codes match `12345678Z`. Numbers with a median between 30 and 130 could be weights in kg, and
between 140 and 210 heights in cm. Five-digit numbers could be postcodes. That is how an
undocumented HL7 `Z` segment can still be understood, and why such a match is always flagged for
review.

Evidence also records the **role**, meaning whose data it is. `PV1-7` is the doctor, and `NK1` is
a relative. A doctor's surname has the same name as the patient's surname, but it belongs to
someone else.

### 6.2 Score: every column against every target

`score()` gives each (column, target) pair a number between 0 and 0.99:

```
start   with evidence for the target's concept:   0.55 + 0.35 × weight   (+0.04 if standard)
        with no concept (no pack):                  name similarity (below)
minus   0.1 × the strongest evidence for a different concept         (the column might mean something else)
minus   0.35 if the column belongs to another role                    (the doctor's surname for the patient's)
minus   0.3  if the type can't fit (text → date)
minus   0.3  if the unit is different and there is no conversion
minus   0.5  if the column is empty
minus   0.2 × the share of empty cells
minus   0.1  if the cell holds several values and the target takes one
plus/minus   whatever the pack adds (score_adjust)
```

So a standard position scores 0.94, a name match 0.90, and a detector with weight 0.4 scores 0.69.

**With no pack** (the orders example), there is no vocabulary, so names are the only evidence.
`name_match()` compares the column name with the target name **word by word**, and also with the
names of the objects the target sits under. "NIF cliente" matches `cliente.nif`, and "Num. pedido"
matches `numero` under `pedido`. Cut words count (`num` / `numero`). An abbreviation counts a
little less (`dto` / `descuento`) and is always flagged for review. A column that names a
different object of the destination loses points: "Fecha entrega" is not the order's `fecha` when
the destination also has an `entrega` object.

The pack can also offer **composites**, meaning several columns that together make one value. For
example, the doctor's given name and surname (`PV1-7.3 + PV1-7.2`), or the first and second
surname in separate columns.

### 6.3 Assignment: one column, one field

All pairs are sorted from best to worst and taken greedily. A target takes its best pair if the
score is at least **0.6** and none of its columns is taken yet. One exception: a full-name column
("Nombre y apellidos") may feed both the given name and the surnames, because the code splits it.

### 6.4 Transforms: how the value is converted

`transforms_for()` reads the profile, never the model:

| Situation | Transform |
|---|---|
| date column with a known format | `date` from that format to ISO |
| a column mixing `dd/mm/yyyy` and `yyyy-mm-dd` | `date` trying each format in order, with an issue saying so |
| 8-digit numbers such as `19850412` for a date target | `date %Y%m%d`, with an issue, since the format didn't say they were dates |
| decimal comma | `number` with `decimal: ","` |
| `g` → `kg`, `m` → `cm`, `lb` → `kg` | `scale`. Values that look like metres or grams but have no unit in the label get converted too, with an issue |
| target with allowed values | `translate`, through the pack's tables |
| target wants title case and the values are in capitals | `title` (`PABLO MARTINEZ` → `Pablo Martinez`; particles such as `de` stay lowercase) |
| target pattern starts with `\+` | `phone` (`600111222` → `+34600111222`, with an issue if the country is assumed) |
| target pattern is `[0-9]{5}` and the column is a number | `pad` (`3001` → `03001`) |
| several columns | `join_columns` |
| full name into given name or surnames | `name_part` (given names, then two surnames, Spanish convention) |
| list target and cells such as `HTA; DLP` | `split_values` |
| several values in a cell and a target that takes one | `first`, with an issue (or pending, if the first could be the wrong one) |

**Translations never guess.** Sex codes are read as `male`, `female`, `other` or `unknown`, then
written the way the destination's catalogue writes them (`Mujer`, `female`...). A lone `M` is
`mujer` in the Spanish convention (H/M) and `male` in the English one (M/F). If the other values
in the column don't settle which convention it is, `M` stays untranslated and the field becomes
pending.

### 6.5 Status: when a field becomes pending

A chosen field starts as **mapped** and becomes **pending** if any of these apply:

- a value has no translation into the allowed values;
- another free column scores within 0.02 (`empate con …: elegir cuál`), for example a home phone
  and a mobile phone;
- only a section or a description names it, not the column itself;
- with no pack, the match is a guess: an abbreviation, a column named after the object
  ("Cliente" for `cliente.nombre`), or a column that names another object;
- a date column has a shape nobody recognises;
- the column holds different measurements in different rows (`OBX-5` with no code filter);
- several identifiers share one cell with no type code to tell them apart.

Some issues are shown without making the field pending: "deducido solo por los valores: revisar"
(inferred from the values only) and "campo personalizado del centro" (a custom field).

A target with no column above 0.6 is **no_data**. It is **pending** instead when it is required,
or when the pack knows the data may be there but not usable as is (an observation that needs a
code filter). With no pack, a column scoring 0.4 or more is offered as `quizá …: revisar`.

## 7. Worked examples: real decisions

These are the rules proposer's actual answers (`matcher.propose`). Reasons and issues are shown as
the app writes them, in Spanish.

### HL7 v2.3 feed → `cdss_paciente` (clinical pack)

| Target | From | Score | Why | What happens |
|---|---|---|---|---|
| `paciente.nombre` | `PID-5.2` | 0.94 | posición estándar (PID-5.2) | `title`: the feed is in capitals |
| `paciente.fecha_nacimiento` | `PID-7` | 0.94 | posición estándar (PID-7) | `date` from `%Y%m%d` |
| `paciente.sexo` | `PID-8` | 0.94 | posición estándar (PID-8) | `translate` into the allowed values |
| `direccion.codigo_postal` | `PID-11.5` | 0.89 | posición estándar (PID-11.5) | `pad` to 5 digits |
| `datos_clinicos.grupo_sanguineo` | `ZPA-2` | 0.865 | los valores son grupos sanguíneos | a `Z` segment with no documentation: flagged as inferred from values and as a custom field |
| `datos_clinicos.peso_kg` | `ZPA-3` | 0.69 | números con mediana 70.4: rango típico de peso en kg | weaker evidence, so a lower score, with the same two flags |
| `datos_clinicos.medico_responsable` | `PV1-7.3` + `PV1-7.2` | 0.82 | nombre y apellidos del médico en columnas separadas: se unen | `join_columns`, then `title`. The doctor's surname never reaches `paciente.apellidos`, because of the role penalty |

### Hand-made Excel (`hospital_c_messy.xlsx`) → the same destination

| Target | From | Score | Why | What happens |
|---|---|---|---|---|
| `paciente.id` | `Paciente / NHC` | 0.90 | el nombre contiene «nhc» | a name match |
| `paciente.nombre` | `Paciente / Nombre y apellidos` | 0.80 | el nombre contiene «nombre» | 0.90 minus 0.1, because the column also says «apellidos». `name_part` splits it: issue "revisar nombres compuestos" |
| `paciente.apellidos` | the same column | 0.80 | el nombre contiene «apellidos» | the other half of the split |
| `datos_clinicos.peso_kg` | `Antropometría / Peso (kg)` | 0.90 | el nombre contiene «peso» | the merged group header became part of the label |
| `paciente.dni`, `direccion.*`, … | none | none | ninguna columna supera el umbral | **no_data**: this file doesn't have them, and nothing is invented |

### CSV order lines → nested JSON, with no pack

| Target | From | Score | Status | Why / issue |
|---|---|---|---|---|
| `numero` | `Num. pedido` | 0.82 | mapped | nombre casi igual (`num` is a cut of `numero`, and `pedido` names the object) |
| `fecha` | `Fecha pedido` | 0.85 | mapped | the column mixes `dd-mm-yyyy`, `dd/mm/yyyy` and `yyyy-mm-dd`: each is tried in order |
| `cliente.nif` | `NIF cliente` | 0.90 | mapped | mismo nombre |
| `cliente.nombre` | `Cliente` | 0.70 | **pending** | la columna lleva el nombre de «cliente»: a guess, so the reviewer decides |
| `lineas[].descuento_pct` | `% Dto.` | 0.72 | **pending** | abreviatura en el nombre de la columna: `dto` might be `descuento` |

`"$group_by": "numero"` then turns the lines into one order each, with its customer and a list of
lines. If two lines of the same order disagree about the customer, the engine sets them aside.

## 8. The AI proposer

`proposer.py` asks a local Qwen model, through Ollama on `127.0.0.1` only, to choose the columns.

**What the model sees** (`aiview.py`, default deny). The model sees column names, descriptions,
types, formats, units and empty ratios, plus:
- *real values* only for short, harmless category lists (`H/M`, `A+/0-`), at most 12 values;
- *min / median / max* for measurements that aren't personal;
- for domain terms, how many were recognised, never the text;
- for everything else, *masked samples*: `FERNANDEZ ALVAREZ` → `XXXXXXXXX XXXXXXX`,
  `14/02/1978` → `99/99/9999`.

Example values from the destination are masked the same way.

**What it may answer.** A JSON schema lists the real column names and the real targets, so the
model can't invent either. Approved recipes for the same destination are added as worked examples,
which is how it learns an organisation's habits without retraining.

**What the code checks afterwards.** Anything doubtful becomes pending:
- columns that don't exist, or a column used twice;
- "mapped" with no column, or a required field answered as "no data";
- "no data" where the rules found a strong match (0.85 or more);
- a column whose evidence clearly means another concept (a technical `id` as the patient
  identifier, or a diagnosis column as the doctor);
- translations outside the allowed values. The model's translations are used only for values the
  rules couldn't translate, and are flagged "propuesta por la IA (revisar)".

Structure stays the code's call even with the AI. A full-name column is split as in the rules, a
list takes every column the rules found for it, and joined columns are ordered given name first.

**Two passes.** The first pass runs with thinking off, which is fast. Fields left pending or below
0.7 are asked again with thinking on, using only the columns still free. With `auto`, if Ollama
isn't running, the rules answer instead and the proposal says why.

## 9. Confidence: what the number means

The score is a hand-weighted rule. It orders the review, but **it is not a probability.** To give
it a meaning, `evalset/` generates 1,200 messy files from invented records whose correct output is
known. Every proposal is graded by the values it would really write, not by its column name.

`scripts/calibrate.py` counts how often each score band was right on one half of the files and
checks the result on the other half. The review screen then shows "en pruebas sintéticas,
propuestas así acertaron 96 de cada 100" ("in synthetic tests, proposals like this were right 96
times in 100"). For the rules, accepting a proposal as is was right 95–97% of the time between
0.6 and 0.8, and over 99.8% above 0.8. Wrong values that pass every check were 3 out of 16,080
fields. The figures and their limits are in [CALIBRATION.md](CALIBRATION.md). Real exports can be
harder than the generator, and the screen says so.

## 10. Review, approval and reuse

In the web app, each field shows its source, its reasons, its issues and a before → after preview
computed by the engine. The reviewer can switch to any ranked candidate (`matcher.ranking`).

At approval (`recipe.py`):
- nothing may be pending;
- every source column that wasn't used is **carried** (into the destination's slot for extras: a
  FHIR extension, an extra column or an element) or **dropped**, and the recipe records which and
  who decided;
- every field whose decision differs from the proposal gets `changed_by`;
- the recipe is sealed with the reviewer's name, the time and a SHA-256 of its decisions. Editing
  a decision afterwards breaks the seal.

**Reuse.** A recipe records its source format and a signature: the columns it uses and their
types. When a new file has the same format, the same destination and those columns with compatible
types, the recipe is applied directly, with no proposal and no AI. Changing the destination's
example or rules changes its id, so old recipes stop matching instead of writing the wrong shape.

## 11. The engine

`engine.py` applies an approved recipe row by row. It uses no AI, does no joins and makes no
guesses:

1. For each target, it takes the values of the `from` columns and applies the transforms in order.
2. It checks the result against the destination: type, allowed values, pattern, range, required.
3. A row that breaks a rule is **set aside with the reason** and never silently fixed. The report
   lists positions and reasons only, never the values.
4. With `$group_by`, rows with the same key become one item. Fields inside the repeated group give
   one entry per row, and fields outside it must agree.
5. The format's writer renders the items like the example, and its checker validates the file.

## Design decisions

The choices that shape everything above, and why:

| Decision | Why |
|---|---|
| **All joins happen when reading, not in the engine** | the proposer and the engine see the same simple rows whatever the format, so nothing downstream is format-specific |
| **The destination is an example of the output** | showing one record is easier than writing a schema, and the output can copy its style |
| **A format plug-in is a reader + writer + checker** | N formats need N plug-ins, not N × N converters |
| **Generic core + domain packs** | the core knows structure only; clinical knowledge (vocabulary, ICD-10, LOINC, roles) lives in `packs/clinical/` and another domain is another pack |
| **The model picks columns, the code picks formats** | judgement where it helps, exactness where it matters; the model can't write a wrong date pattern |
| **The AI is local and sees masked data** | personal data never leaves the machine, and the model gets no real identifiers even locally |
| **Thinking only for doubtful fields** | `qwen3:8b` on modest hardware stays fast; the slow pass runs where it can change the outcome |
| **Doubt becomes pending, never a guess** | a field left for a human costs a minute, while a silent wrong value reaches the destination |
| **No source column is dropped silently** | every unused column is carried or dropped on purpose, and the recipe records who decided |
| **A human approves, and the recipe is sealed** | each decision has an author and can be traced; a sealed recipe can be reused safely |

## Where to change things

| To change | Edit |
|---|---|
| synonyms and standard positions of a concept | `packs/clinical/vocabulary.py` (`CONCEPTS`) |
| what values look like a concept | `from_values` in the same file |
| value translations (sex, blood group) | `translate` in the same file |
| a domain's special cases | the hooks of `Pack` in `packs/__init__.py` (all no-ops by default) |
| score weights and the 0.6 threshold | `score` and `THRESHOLD` in `matcher.py` |
| which transforms are chosen | `transforms_for` in `matcher.py` |
| what the model sees | `aiview.py` |
| the prompt and the checks on the model's reply | `proposer.py` (and the pack's `system_prompt`) |
| a new format | a `Format` subclass in `formats/`, registered in `FORMATS` |

After a change, `pytest` runs the golden tests for the three hospitals and the FHIR Bundles, and
`scripts/calibrate.py` shows whether the scores still mean what the screen says.
