# Proposer evaluation

*Generated 2026-10-24 by `scripts/eval_proposer.py`. Synthetic data only.*

Each golden field is **right** (same decision as the reviewed plan), **pending** (left for a human: costs time, not safety) or **wrong** (a reviewer must catch it).

| proposer | file | right | pending | wrong | seconds |
|---|---|---|---|---|---|
| rules | hospital_alvarez_buylla.csv | 15/15 | 0 | 0 | 0.0 |
| rules | hospital_leon_fhir.json | 15/15 | 0 | 0 | 0.0 |
| rules | huca_oviedo_hl7v23.hl7 | 15/15 | 0 | 0 | 0.0 |
| qwen3:8b | hospital_alvarez_buylla.csv | 15/15 | 0 | 0 | 117.3 |
| qwen3:8b | hospital_leon_fhir.json | 15/15 | 0 | 0 | 81.4 |
| qwen3:8b | huca_oviedo_hl7v23.hl7 | 15/15 | 0 | 0 | 54.5 |
| qwen3:30b (2026-10-21, before phases 7–8; not re-run) | hospital_alvarez_buylla.csv | 14/15 | 0 | 1 | 161.7 |
| qwen3:30b (2026-10-21, before phases 7–8; not re-run) | hospital_leon_fhir.json | 14/15 | 0 | 1 | 192.5 |
| qwen3:30b (2026-10-21, before phases 7–8; not re-run) | huca_oviedo_hl7v23.hl7 | 15/15 | 0 | 0 | 72.6 |

## Differences from the reviewed plans

None.

## Files without a reviewed plan (no ground truth: check by hand)

- **rules, hospital_c_messy.xlsx** (0.0 s): 7 mapped, 8 no data, 0 pending. id←Paciente / NHC, nombre←Paciente / Nombre y apellidos, apellidos←Paciente / Nombre y apellidos, fecha_nacimiento←Paciente / F. Nac., sexo←Paciente / Sexo, peso_kg←Antropometría / Peso (kg), altura_cm←Antropometría / Talla (cm)
- **rules, hospital_a_diagnosticos.hl7** (0.0 s): 13 mapped, 1 no data, 1 pending. dni←PID-19, nombre←PID-5.2, apellidos←PID-5.1, fecha_nacimiento←PID-7, sexo←PID-8, telefono←PID-13, calle←PID-11.1, ciudad←PID-11.3, codigo_postal←PID-11.5, peso_kg←OBX-5 [OBX-3.1=29463-7], altura_cm←OBX-5 [OBX-3.1=8302-2], alergia←AL1-3.2, medico_responsable←PV1-7.3+PV1-7.2
- **rules, hospital_b_condiciones.json** (0.0 s): 6 mapped, 9 no data, 0 pending. id←identifier[mrn].value, nombre←name.given, apellidos←name.family, fecha_nacimiento←birthDate, sexo←gender, alergia←AllergyIntolerance.code.text
- **qwen3:8b, hospital_c_messy.xlsx** (101.6 s): 7 mapped, 6 no data, 2 pending. id←Paciente / NHC, nombre←Paciente / Nombre y apellidos, apellidos←Paciente / Nombre y apellidos, fecha_nacimiento←Paciente / F. Nac., sexo←Paciente / Sexo, peso_kg←Antropometría / Peso (kg), altura_cm←Antropometría / Talla (cm)
- **qwen3:8b, hospital_a_diagnosticos.hl7** (70.5 s): 13 mapped, 1 no data, 1 pending. dni←PID-19, nombre←PID-5.2, apellidos←PID-5.1, fecha_nacimiento←PID-7, sexo←PID-8, telefono←PID-13, calle←PID-11.1, ciudad←PID-11.3, codigo_postal←PID-11.5, peso_kg←OBX-5 [OBX-3.1=29463-7], altura_cm←OBX-5 [OBX-3.1=8302-2], alergia←AL1-3.2, medico_responsable←PV1-7.3+PV1-7.2
- **qwen3:8b, hospital_b_condiciones.json** (65.9 s): 6 mapped, 5 no data, 4 pending. id←identifier[mrn].value, nombre←name.given, apellidos←name.family, fecha_nacimiento←birthDate, sexo←gender, alergia←AllergyIntolerance.code.text
