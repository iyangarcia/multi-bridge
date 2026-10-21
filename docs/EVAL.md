# Proposer evaluation

*Generated 2026-10-21 by `scripts/eval_proposer.py`. Synthetic data only.*

Each golden field is **right** (same decision as the reviewed plan), **pending** (left for a human: costs time, not safety) or **wrong** (a reviewer must catch it).

| proposer | file | right | pending | wrong | seconds |
|---|---|---|---|---|---|
| rules | hospital_alvarez_buylla.csv | 15/15 | 0 | 0 | 0.0 |
| rules | hospital_leon_fhir.json | 15/15 | 0 | 0 | 0.0 |
| rules | huca_oviedo_hl7v23.hl7 | 15/15 | 0 | 0 | 0.0 |
| qwen3:8b | hospital_alvarez_buylla.csv | 15/15 | 0 | 0 | 27.5 |
| qwen3:8b | hospital_leon_fhir.json | 14/15 | 0 | 1 | 59.7 |
| qwen3:8b | huca_oviedo_hl7v23.hl7 | 15/15 | 0 | 0 | 55.5 |
| qwen3:30b | hospital_alvarez_buylla.csv | 14/15 | 0 | 1 | 161.7 |
| qwen3:30b | hospital_leon_fhir.json | 14/15 | 0 | 1 | 192.5 |
| qwen3:30b | huca_oviedo_hl7v23.hl7 | 15/15 | 0 | 0 | 72.6 |

## Differences from the reviewed plans

- **qwen3:8b, hospital_leon_fhir.json**: wrong datos_clinicos.medico_responsable: id+identifier[mrn].system+identifier[mrn].system (revisado: no_data)
- **qwen3:30b, hospital_alvarez_buylla.csv**: wrong paciente.telefono: no_data (revisado: Teléfono móvil)
- **qwen3:30b, hospital_leon_fhir.json**: wrong paciente.id: id (revisado: identifier[mrn].value)

## Files without a reviewed plan (no ground truth: check by hand)

- **rules, hospital_c_messy.xlsx** (0.0 s): 7 mapped, 7 no data, 1 pending. id←Paciente / NHC, nombre←Paciente / Nombre y apellidos, fecha_nacimiento←Paciente / F. Nac., sexo←Paciente / Sexo, peso_kg←Antropometría / Peso (kg), altura_cm←Antropometría / Talla (cm), medico_responsable←Clínica / Diagnóstico principal
- **rules, hospital_a_diagnosticos.hl7** (0.0 s): 12 mapped, 2 no data, 1 pending. id←PID-3.1, dni←PID-19, nombre←PID-5.2, apellidos←PID-5.1, fecha_nacimiento←PID-7, sexo←PID-8, telefono←PID-13, calle←PID-11.1, ciudad←PID-11.3, codigo_postal←PID-11.5, alergia←AL1-3.2, medico_responsable←PV1-7.3+PV1-7.2
- **rules, hospital_b_condiciones.json** (0.0 s): 6 mapped, 9 no data, 0 pending. id←identifier[mrn].value, nombre←name.given, apellidos←name.family, fecha_nacimiento←birthDate, sexo←gender, alergia←AllergyIntolerance.code.text
- **qwen3:8b, hospital_c_messy.xlsx** (172.7 s): 6 mapped, 8 no data, 1 pending. id←Paciente / NHC, nombre←Paciente / Nombre y apellidos, fecha_nacimiento←Paciente / F. Nac., sexo←Paciente / Sexo, peso_kg←Antropometría / Peso (kg), altura_cm←Antropometría / Talla (cm)
- **qwen3:8b, hospital_a_diagnosticos.hl7** (82.9 s): 12 mapped, 1 no data, 2 pending. id←PID-3.1, dni←PID-19, nombre←PID-5.2, apellidos←PID-5.1, fecha_nacimiento←PID-7, sexo←PID-8, telefono←PID-13, calle←PID-11.1, ciudad←PID-11.3, codigo_postal←PID-11.5, alergia←AL1-3.2, medico_responsable←PV1-7.3+PV1-7.2
- **qwen3:8b, hospital_b_condiciones.json** (153.7 s): 7 mapped, 8 no data, 0 pending. id←identifier[mrn].value, nombre←name.given, apellidos←name.family, fecha_nacimiento←birthDate, sexo←gender, codigo_postal←identifier[mrn].system+identifier[mrn].system, alergia←AllergyIntolerance.code.text
- **qwen3:30b, hospital_c_messy.xlsx** (229.8 s): 6 mapped, 8 no data, 1 pending. id←Paciente / NHC, nombre←Paciente / Nombre y apellidos, fecha_nacimiento←Paciente / F. Nac., sexo←Paciente / Sexo, peso_kg←Antropometría / Peso (kg), altura_cm←Antropometría / Talla (cm)
- **qwen3:30b, hospital_a_diagnosticos.hl7** (159.0 s): 12 mapped, 1 no data, 2 pending. id←PID-3.1, dni←PID-19, nombre←PID-5.2, apellidos←PID-5.1, fecha_nacimiento←PID-7, sexo←PID-8, telefono←PID-13, calle←PID-11.1, ciudad←PID-11.3, codigo_postal←PID-11.5, alergia←AL1-3.2, medico_responsable←PV1-7.3+PV1-7.2
- **qwen3:30b, hospital_b_condiciones.json** (227.9 s): 6 mapped, 9 no data, 0 pending. id←id, nombre←name.given, apellidos←name.family, fecha_nacimiento←birthDate, sexo←gender, alergia←AllergyIntolerance.code.text

## History

- **Run 1 (2026-10-21), before the cross-checks.** The table above. The safety checks added afterwards turn each listed *wrong* into *pending*; a re-run is needed to confirm (ROADMAP phase 2).
