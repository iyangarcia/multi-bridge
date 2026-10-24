"""Phase 9: the generated evaluation set, its grading, the calibration and the matcher fixes it found."""

import datetime as dt

import pytest

from evalset import DOMAINS, cases, formats, generate
from evalset.grade import bands, check, fit, grade, read, wilson
from multibridge import calibration
from multibridge.expected import Expected
from multibridge.matcher import name_match, other_objects, propose, transforms_for
from multibridge.parsers import parse_bytes
from multibridge.records import to_rows

PAIRS = [(d, f) for d in DOMAINS for f in formats(d)]


def test_every_format_of_both_domains_is_generated():
    assert set(formats("pacientes")) == {"csv", "xlsx", "json", "xml", "hl7", "fhir"}
    assert set(formats("pedidos")) == {"csv", "xlsx", "json", "xml"}
    assert Expected.load(generate("pacientes", "csv", 0).destination).pack == "clinical"
    assert Expected.load(generate("pedidos", "csv", 0).destination).pack is None


@pytest.mark.parametrize("domain,fmt", PAIRS)
def test_a_seed_gives_the_same_file(domain, fmt):
    a, b = generate(domain, fmt, 5), generate(domain, fmt, 5)
    assert a.data == b.data and a.truth == b.truth and a.values == b.values
    assert generate(domain, fmt, 6).values != a.values


@pytest.mark.parametrize("domain,fmt", PAIRS)
def test_the_truth_points_at_real_columns(domain, fmt):
    for seed in range(8):
        case = generate(domain, fmt, seed)
        rows, expected = read(case)           # one source row per generated record
        assert {t.path for t in expected.targets} == set(case.truth)
        for target, cols in case.truth.items():
            assert all(c in rows.columns for c in cols), (case.label, target, cols)
            if not cols:                      # nothing in the file: the correct output is empty
                assert all(v[target] is None for v in case.values)


def test_the_true_columns_give_the_true_values():
    """With the true columns and the transforms the rules pick for them (the oracle), almost every field
    comes out exactly right: the generator and the grading agree with the engine."""
    right = total = 0
    for case in cases(40, start=500):
        for g in grade(case, propose(*read(case))):
            if g["oracle"] is not None:
                total += 1
                right += g["oracle"]
    assert right / total >= 0.97


def test_grading_by_output_values():
    case = generate("pacientes", "csv", 3)
    rows, expected = read(case)
    t = expected.get("paciente.fecha_nacimiento")
    col = case.truth[t.path][0]
    transforms, _, _ = transforms_for(rows, [col], t)
    assert check(rows, {"from": [col], "transforms": transforms}, t, case) == "ok"
    # the same column with no date transform breaks the destination's rule: the engine sets it aside
    raw = {"from": [col], "transforms": []}
    if rows.columns[col].format != "yyyy-mm-dd":
        assert check(rows, raw, t, case) == "caught"
    # another column whose values pass every rule: silently wrong, the dangerous kind
    city = expected.get("direccion.ciudad")
    other = case.truth["paciente.nombre"][0]
    assert check(rows, {"from": [other], "transforms": []}, city, case) == "silent"


def test_outcomes_of_a_draft():
    case = generate("pedidos", "csv", 2)
    rows, expected = read(case)
    draft = propose(rows, expected)
    present = next(t for t, cols in case.truth.items() if cols)
    draft["fields"][present].update(status="no_data", **{"from": []}, transforms=[])
    graded = {g["target"]: g for g in grade(case, draft, rows, expected)}
    assert graded[present]["outcome"] == "missed"
    assert all(g["outcome"] in ("right", "pending", "missed", "wrong") for g in graded.values())


def test_wilson_interval_and_monotone_fit():
    assert wilson(0, 0) == (0.0, 1.0)
    low, high = wilson(9, 10)
    assert 0.55 < low < 0.9 < high <= 1.0
    pts = [(0.65, True)] * 9 + [(0.65, False)] + [(0.75, True)] * 7 + [(0.75, False)] * 3 + [(0.95, True)] * 10
    table = fit(bands(pts, [0.6, 0.7, 0.8, 0.9, 1.0]))
    rates = [b["calibrated"] for b in table if b["calibrated"] is not None]
    assert rates == sorted(rates) and rates[0] == 0.8 and rates[-1] == 1.0   # 0.9 then 0.7 pooled to 0.8
    assert table[2]["calibrated"] is None                                     # an empty band says nothing


def test_measured_rate_lookup(monkeypatch):
    fake = {"rules": {"bands": [{"low": 0.6, "high": 0.8, "n": 50, "rate": 0.9, "interval": [0.79, 0.96]},
                                {"low": 0.8, "high": 1.0, "n": 0, "rate": None, "interval": [0, 1]}]}}
    monkeypatch.setattr(calibration, "table", lambda: fake)
    assert calibration.measured(0.7, "rules")["rate"] == 0.9
    assert calibration.measured(0.9, "rules") is None          # never measured: no rate
    assert calibration.measured(0.7, "qwen3:8b") is None
    assert calibration.measured(None, "rules") is None


def test_the_shipped_table_is_monotone():
    for proposer, entry in calibration.table().items():
        rates = [b["rate"] for b in entry["bands"] if b["rate"] is not None]
        assert rates == sorted(rates), proposer


# --- what the set found in the matcher ----------------------------------------------------------------

def rows_of(text: str):
    return to_rows(parse_bytes(text.encode("utf-8"), "x.csv"))


CDSS = Expected.load(generate("pacientes", "csv", 0).destination)


def test_phones_with_spaces_or_0034_are_converted():
    rows = rows_of("NHC;Teléfono\n1;0034600112233\n2;+34 600 44 55 66\n")
    transforms, _, _ = transforms_for(rows, ["Teléfono"], CDSS.get("paciente.telefono"))
    assert {"op": "phone", "country": "34"} in transforms


def test_eight_digit_dates_outside_hl7():
    rows = rows_of("NHC;FNAC\n1;19850412\n2;20010907\n")
    transforms, issues, _ = transforms_for(rows, ["FNAC"], CDSS.get("paciente.fecha_nacimiento"))
    assert {"op": "date", "from": "%Y%m%d"} in transforms and any("aaaammdd" in i for i in issues)
    rows = rows_of("NHC;FNAC\n1;12345678\n2;20010907\n")      # not all dates: left alone
    assert not any(t["op"] == "date" for t in transforms_for(rows, ["FNAC"], CDSS.get("paciente.fecha_nacimiento"))[0])


def test_a_section_prefix_is_not_the_field():
    rows = rows_of("NHC;Dirección / Calle;Dirección / CP;Dirección / CPOSTAL\n1;C/ Uría 1;33001;33001\n"
                   "2;C/ Mayor 2;33002;33002\n")
    draft = propose(rows, CDSS)
    assert draft["fields"]["direccion.calle"]["from"] == ["Dirección / Calle"]
    assert draft["fields"]["direccion.codigo_postal"]["from"] == ["Dirección / CP"]


def test_english_full_name_is_split():
    rows = rows_of("Patient ID;Full name\nP1;Ana Pérez Gil\nP2;Lucía María Álvarez Castro\n")
    fields = propose(rows, CDSS)["fields"]
    assert fields["paciente.nombre"]["from"] == fields["paciente.apellidos"]["from"] == ["Full name"]
    assert fields["paciente.apellidos"]["transforms"][0]["op"] == "name_part"


def test_a_column_naming_another_object_is_a_guess():
    e = Expected.load(generate("pedidos", "csv", 0).destination)
    t = e.get("fecha")
    assert name_match("Fecha entrega", t, other_objects(e)["fecha"])[2]     # "entrega" is another object
    assert name_match("Fecha pedido", t, other_objects(e)["fecha"])[2] is None
    rows = rows_of("Num. pedido;Fecha entrega;Ref.\nP-1;01/02/2026;A\nP-2;03/02/2026;B\n")
    assert propose(rows, e)["fields"]["fecha"]["status"] == "pending"


def test_no_silent_mistakes_on_fresh_files():
    """The safety bar on files no fix was tuned on: whatever the rules map, nothing silently wrong."""
    silent = [g for case in cases(60, start=4000) for g in grade(case, propose(*read(case))) if g["silent"]]
    assert silent == []


def test_dates_are_iso_in_the_truth():
    case = generate("pedidos", "xlsx", 1)
    assert all(v["fecha"] is None or dt.date.fromisoformat(v["fecha"]) for v in case.values)
