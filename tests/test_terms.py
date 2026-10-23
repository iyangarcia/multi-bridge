import pytest

from multibridge.packs.clinical.terms import get_normalizer

N = get_normalizer()


def one(text):
    (m,) = N.normalize(text)
    return m


@pytest.mark.parametrize("text, code, method", [
    ("DM2", "E11", "abbreviation"),
    ("Diabetes mellitus tipo II", "E11", "exact"),
    ("Hipertensión arterial", "I10", "exact"),
    ("E11.9", "E11.9", "code"),
    ("diabetis tipo 2", "E11", "fuzzy"),
    ("paciente con epoc", "J44", "contains"),
    ("ITU por E. coli", "N39.0", "contains"),
    ("Sepsis, no especificada", "A41", "exact"),
])
def test_recognised(text, code, method):
    m = one(text)
    assert (m.status, m.code, m.method) == ("matched", code, method)


def test_fuzzy_similarity_is_reported_not_a_probability():
    m = one("diabetis tipo 2")
    assert 0.85 <= m.similarity < 1


@pytest.mark.parametrize("text, qualifier", [
    ("Sospecha de NAC", "suspected"),
    ("¿NAC?", "suspected"),
    ("AP de IAM", "history"),
    ("Antecedentes familiares de diabetes tipo 2", "family"),
    ("No HTA", "negated"),
    ("EPOC descartada", "negated"),
])
def test_qualifiers_change_clinical_meaning(text, qualifier):
    m = one(text)
    assert m.status == "matched" and m.qualifier == qualifier


def test_modifiers_are_kept_not_lost():
    m = one("Reagudización de EPOC")
    assert m.code == "J44" and m.modifiers == ["reagudizacion de"]
    assert one("DM2 mal controlada").modifiers == ["mal controlada"]


def test_several_diagnoses_in_one_cell():
    ms = N.normalize("AP de IAM; HTA")
    assert [(m.code, m.qualifier) for m in ms] == [("I21", "history"), ("I10", "confirmed")]
    assert [m.code for m in N.normalize("DM2 e HTA")] == ["E11", "I10"]


@pytest.mark.parametrize("text", ["IRA", "IC", "FA", "ACV"])
def test_ambiguous_abbreviations_are_never_auto_resolved(text):
    m = one(text)
    assert m.status == "ambiguous" and len(m.alternatives) >= 2 and m.code is None


def test_unknown_local_abbreviation_asks_a_human():
    m = one("DiabA")
    assert m.status == "unknown" and "aclaración" in m.note


def test_other_terminologies_are_flagged_not_guessed():
    assert "SNOMED" in one("38341003").note
    assert "LOINC" in one("29463-7").note


def test_unknown_normalizer_name():
    with pytest.raises(ValueError):
        get_normalizer("nope")
