"""Tiny Spanish seed terminology for demos and tests.

ICD-10 categories (mostly 3-character) with Spanish synonyms and the
abbreviations used in Spanish clinical notes. It is a DEMO seed, not a
validated terminology: before real use, load the official CIE-10-ES release
(Ministerio de Sanidad) and/or SNOMED CT Spanish edition, which Spain licenses
free of charge as a SNOMED International member.
"""

SYSTEM = "ICD-10"

# code -> (display, synonyms). Written naturally; normalised at load time.
CONCEPTS: dict[str, tuple[str, list[str]]] = {
    "E10": ("Diabetes mellitus tipo 1", [
        "diabetes mellitus tipo 1", "diabetes tipo 1", "diabetes tipo I", "diabetes insulinodependiente",
        "diabetes mellitus insulinodependiente", "diabetes juvenil", "dm tipo 1", "dm tipo I"]),
    "E11": ("Diabetes mellitus tipo 2", [
        "diabetes mellitus tipo 2", "diabetes tipo 2", "diabetes tipo II", "diabetes mellitus tipo II",
        "diabetes no insulinodependiente", "diabetes mellitus no insulinodependiente", "diabetes del adulto",
        "dm tipo 2", "dm tipo II"]),
    "E66": ("Obesidad", ["obesidad", "obesidad mórbida"]),
    "E78": ("Trastornos del metabolismo de las lipoproteínas (dislipemia)", [
        "dislipemia", "dislipidemia", "hipercolesterolemia", "hiperlipemia"]),
    "I10": ("Hipertensión esencial (primaria)", [
        "hipertensión arterial", "hipertensión esencial", "hipertensión", "hipertensión arterial esencial"]),
    "I21": ("Infarto agudo de miocardio", ["infarto agudo de miocardio", "infarto de miocardio", "infarto cardiaco"]),
    "I48": ("Fibrilación y aleteo auricular", ["fibrilación auricular", "arritmia completa por fibrilación auricular",
                                              "flutter auricular", "aleteo auricular"]),
    "I50": ("Insuficiencia cardiaca", ["insuficiencia cardiaca", "insuficiencia cardiaca congestiva",
                                       "fallo cardiaco"]),
    "I61": ("Hemorragia intracerebral", ["hemorragia intracerebral", "ictus hemorrágico", "hemorragia cerebral"]),
    "I63": ("Infarto cerebral", ["infarto cerebral", "ictus isquémico", "accidente cerebrovascular isquémico"]),
    "J18": ("Neumonía, organismo no especificado", ["neumonía", "neumonía adquirida en la comunidad",
                                                    "neumonía comunitaria"]),
    "J44": ("Enfermedad pulmonar obstructiva crónica", ["enfermedad pulmonar obstructiva crónica",
                                                       "bronquitis crónica obstructiva"]),
    "J45": ("Asma", ["asma", "asma bronquial"]),
    "J96.0": ("Insuficiencia respiratoria aguda", ["insuficiencia respiratoria aguda", "fallo respiratorio agudo"]),
    "N17": ("Insuficiencia renal aguda", ["insuficiencia renal aguda", "fracaso renal agudo", "lesión renal aguda"]),
    "N18": ("Enfermedad renal crónica", ["enfermedad renal crónica", "insuficiencia renal crónica"]),
    "N39.0": ("Infección del tracto urinario, sitio no especificado", [
        "infección del tracto urinario", "infección urinaria", "infección de orina"]),
    "A04.7": ("Enterocolitis debida a Clostridioides difficile", [
        "enterocolitis por clostridium difficile", "infección por clostridium difficile", "colitis por c difficile",
        "infección por clostridioides difficile"]),
    "A15": ("Tuberculosis respiratoria", ["tuberculosis pulmonar", "tuberculosis respiratoria", "tuberculosis"]),
    "A41": ("Otras sepsis", ["sepsis", "septicemia", "shock séptico"]),
    "B20": ("Enfermedad por virus de la inmunodeficiencia humana", [
        "enfermedad por vih", "infección por vih", "infección por virus de la inmunodeficiencia humana"]),
    "U07.1": ("COVID-19, virus identificado", ["covid 19", "covid", "infección por sars cov 2", "coronavirus"]),
    "F32": ("Episodio depresivo", ["depresión", "episodio depresivo", "síndrome depresivo"]),
    "G30": ("Enfermedad de Alzheimer", ["enfermedad de alzheimer", "alzheimer", "demencia tipo alzheimer"]),
    "C34": ("Neoplasia maligna de bronquios y pulmón", ["cáncer de pulmón", "neoplasia de pulmón",
                                                        "carcinoma pulmonar", "carcinoma de pulmón"]),
    "C50": ("Neoplasia maligna de mama", ["cáncer de mama", "neoplasia de mama", "carcinoma de mama"]),
}

# Unambiguous abbreviations -> code
ABBREVIATIONS: dict[str, str] = {
    "dm1": "E10", "dmid": "E10",
    "dm2": "E11", "dmii": "E11", "dmt2": "E11", "dmni": "E11", "dmnid": "E11",
    "dlp": "E78", "hta": "I10", "iam": "I21", "acxfa": "I48", "icc": "I50",
    "nac": "J18", "epoc": "J44", "fra": "N17", "erc": "N18", "irc": "N18", "itu": "N39.0",
    "tbc": "A15", "vih": "B20",
}

# Abbreviations that mean different things depending on the service. Never auto-resolve these.
AMBIGUOUS: dict[str, list[tuple[str | None, str]]] = {
    "ira": [("N17", "Insuficiencia renal aguda"), ("J96.0", "Insuficiencia respiratoria aguda")],
    "ic": [("I50", "Insuficiencia cardiaca"), (None, "Interconsulta (no es un diagnóstico)")],
    "fa": [("I48", "Fibrilación auricular"), (None, "Fosfatasa alcalina (dato de laboratorio)")],
    "acv": [("I63", "Infarto cerebral"), ("I61", "Hemorragia intracerebral")],
    "ictus": [("I63", "Infarto cerebral"), ("I61", "Hemorragia intracerebral")],
    "tb": [("A15", "Tuberculosis"), (None, "Otra cosa según el servicio (p. ej. tabaco)")],
}
