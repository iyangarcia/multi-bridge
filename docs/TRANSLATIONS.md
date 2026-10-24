# The two first translations (phases 7 and 8)

*Generated 2026-10-24 by `scripts/translations.py`. Synthetic data only.*

Per destination field: **right** (the reviewed decision), **pending** (left for a human: costs time, not safety) or **wrong** (a reviewer must catch it; must stay 0). *Output* is the reviewed recipe run, written in the destination's format and checked by its checker.

A's truth is the reviewed golden plan, drafted by the rules and checked by hand, so the rules' score there guards against regressions rather than measuring them independently; B's truth (`examples/pedidos/answers.json`) was written before any proposal.

| translation | proposer | source | right | pending | wrong | output | seconds |
|---|---|---|---|---|---|---|---|
| A · Excel → FHIR | rules | hospital_c_messy.xlsx → paciente_resumen_fhir.example.json | 12/12 | 0 | 0 | 6 items, 0 set aside, check passed | 0.0 |
| A · Excel → FHIR | rules | h5_excel_dificil.xlsx → paciente_resumen_fhir.example.json | 12/12 | 0 | 0 | 3 items, 0 set aside, check passed | 0.0 |
| B · CSV → JSON | rules | pedidos_lineas.csv → pedido_json.example.json | 9/11 | 2 | 0 | 3 items, 1 set aside, check passed | 0.0 |
| B · CSV → XML | rules | pedidos_lineas.csv → pedido_xml.example.xml | 9/11 | 2 | 0 | 3 items, 1 set aside, check passed | 0.0 |
| A · Excel → FHIR | qwen3:8b | hospital_c_messy.xlsx → paciente_resumen_fhir.example.json | 10/12 | 2 | 0 | 6 items, 0 set aside, check passed | 100.3 |
| A · Excel → FHIR | qwen3:8b | h5_excel_dificil.xlsx → paciente_resumen_fhir.example.json | 11/12 | 1 | 0 | 3 items, 0 set aside, check passed | 77.5 |
| B · CSV → JSON | qwen3:8b | pedidos_lineas.csv → pedido_json.example.json | 11/11 | 0 | 0 | 3 items, 1 set aside, check passed | 23.9 |
| B · CSV → XML | qwen3:8b | pedidos_lineas.csv → pedido_xml.example.xml | 11/11 | 0 | 0 | 3 items, 1 set aside, check passed | 23.2 |

## Fields not right on the first proposal

- **rules, pedidos_lineas.csv → pedido_json.example.json**: pending `cliente.nombre`; pending `lineas[].descuento_pct`
- **rules, pedidos_lineas.csv → pedido_xml.example.xml**: pending `pedido.cliente.nombre`; pending `pedido.lineas.linea[].descuento_pct`
- **qwen3:8b, hospital_c_messy.xlsx → paciente_resumen_fhir.example.json**: pending `Patient.name.given`; pending `AllergyIntolerance.code.text`
- **qwen3:8b, h5_excel_dificil.xlsx → paciente_resumen_fhir.example.json**: pending `Patient.name.given`
