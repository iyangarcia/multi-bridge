from multibridge import load
from multibridge.parsers import parse_bytes
from multibridge.parsers.table import find_tables


# --- CSV ----------------------------------------------------------------------------------------

def test_spanish_csv_semicolon_decimal_comma(examples):
    ds = load(examples / "hospital_alvarez_buylla.csv")
    assert ds.format == "csv"
    rows = ds.tables["hospital_alvarez_buylla"]
    assert len(rows) == 8
    assert rows[0]["Nº Historia"] == "HC-7781"

    peso = ds.get("hospital_alvarez_buylla", "Peso (kg)")
    assert (peso.dtype, peso.format, peso.unit) == ("decimal", "decimal comma", "kg")
    nac = ds.get("hospital_alvarez_buylla", "F. Nacimiento")
    assert (nac.dtype, nac.format) == ("date", "dd/mm/yyyy")
    assert ds.get("hospital_alvarez_buylla", "Sexo").categories == ["H", "M"]


def test_csv_windows_1252_with_title_rows():
    raw = ("Listado urgencias\r\nGenerado 01/03/2026\r\n\r\n"
           "NHC;Diagnóstico;Peso\r\nX1;HTA;70,5\r\nX2;EPOC;80\r\n").encode("cp1252")
    ds = parse_bytes(raw, "urg.csv")
    assert any("cp1252" in n for n in ds.notes)
    assert any("Listado urgencias" in n for n in ds.notes)
    assert ds.tables["urg"] == [
        {"NHC": "X1", "Diagnóstico": "HTA", "Peso": "70,5"},
        {"NHC": "X2", "Diagnóstico": "EPOC", "Peso": "80"},
    ]
    assert ds.get("urg", "Diagnóstico").kind == "clinical_concept"


def test_sparse_group_row_in_csv_becomes_label_prefix():
    grid = [
        ["Paciente", "", "Medidas", ""],
        ["NHC", "Sexo", "Peso (kg)", "Talla (cm)"],
        ["A1", "H", "70", "170"],
    ]
    (t,), _ = find_tables(grid)
    assert t.labels == ["Paciente / NHC", "Paciente / Sexo", "Medidas / Peso (kg)", "Medidas / Talla (cm)"]


# --- Excel --------------------------------------------------------------------------------------

def test_messy_excel_header_groups_footer_and_second_table(examples):
    ds = load(examples / "hospital_c_messy.xlsx")
    assert ds.format == "excel"
    assert set(ds.tables) == {"Ingresos", "Ingresos (tabla 2)", "Leyenda triaje"}

    rows = ds.tables["Ingresos"]
    assert len(rows) == 6, "footer 'Total pacientes' and notes must not become records"
    assert rows[0]["Paciente / NHC"] == "C-0101"
    assert rows[0]["Paciente / F. Nac."] == "1961-03-04"
    assert ds.tables["Ingresos (tabla 2)"] == [
        {"Código": "H", "Significado": "Hombre"}, {"Código": "M", "Significado": "Mujer"}]

    notes = " ".join(ds.notes)
    assert "Listado de ingresos" in notes and "Total pacientes: 6" in notes
    assert "fórmula(s) sin valor calculado" in notes
    assert "oculta" in notes


def test_excel_comments_and_custom_columns(examples):
    ds = load(examples / "hospital_c_messy.xlsx")
    triage = ds.get("Ingresos", "Clínica / Campo libre 1")
    assert "triaje Manchester" in triage.description
    assert ds.get("Ingresos", "Clínica / Diagnóstico principal").description.startswith("Texto libre")
    unnamed = ds.get("Ingresos", "(sin cabecera) columna K")
    assert unnamed.custom and not unnamed.sensitive
    imc = ds.get("Ingresos", "Antropometría / IMC")
    assert imc.dtype == "empty" and "Fórmula" in imc.description


def test_excel_free_text_diagnoses_are_recognised(examples):
    ds = load(examples / "hospital_c_messy.xlsx")
    dx = ds.get("Ingresos", "Clínica / Diagnóstico principal")
    assert dx.kind == "clinical_concept"
    assert dx.concepts["ambiguous"] == ["IRA"]
    other = ds.get("Ingresos", "Clínica / Otros diagnósticos")
    assert other.concepts["unknown"] == ["DiabA"]
