"""The promise to the hospital: the AI sees structure, never personal data."""

import json

import pytest

from multibridge import load
from multibridge.profile import as_ai

FILES = ["hospital_alvarez_buylla.csv", "hospital_leon_fhir.json", "huca_oviedo_hl7v23.hl7",
         "hospital_c_messy.xlsx", "hospital_a_diagnosticos.hl7", "hospital_b_condiciones.json"]


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("level", ["structure", "profile"])
def test_no_sensitive_value_reaches_the_ai(examples, name, level):
    ds = load(examples / name)
    payload = json.dumps(as_ai(ds, level), ensure_ascii=False)
    leaked = []
    for f in ds.fields:
        if not f.sensitive:
            continue
        for v in ds.values(f):
            for x in (v if isinstance(v, list) else [v]):
                if x and len(x) >= 4 and x in payload:
                    leaked.append((f.key, x))
    assert not leaked


@pytest.mark.parametrize("name", FILES)
def test_free_text_diagnoses_are_summarised_not_sent(examples, name):
    ds = load(examples / name)
    payload = json.dumps(as_ai(ds), ensure_ascii=False)
    for f in ds.fields:
        if f.kind == "clinical_concept" and f.concepts:
            for raw in f.concepts["unknown"] + f.concepts["ambiguous"]:
                assert f'"{raw}"' not in payload


def test_expected_identifiers_are_flagged(examples):
    ds = load(examples / "hospital_alvarez_buylla.csv")
    flagged = {f.path for f in ds.fields if f.sensitive}
    assert {"Nº Historia", "DNI", "Nombre", "Apellidos", "F. Nacimiento", "Teléfono móvil", "Domicilio"} <= flagged
    assert not {"Sexo", "Grupo sanguíneo", "Peso (kg)", "Localidad"} & flagged
