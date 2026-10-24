"""Invented patients for expected/cdss_paciente.example.json, as tables, HL7 v2 and FHIR.

Every person, number and address here is made up (docs/COMPLIANCE.md C1).
"""

from __future__ import annotations

import datetime as dt
import json

from . import ROOT, Case
from .render import Column, csv_file, json_file, xlsx_file, xml_file

FORMATS = ("csv", "xlsx", "json", "xml", "hl7", "fhir")
DESTINATION = ROOT / "expected" / "cdss_paciente.example.json"

GIVEN = ["Ana", "Javier", "Lucía", "Marta", "Pablo", "Carmen", "Diego", "Elena", "Sergio", "Laura", "Raúl",
         "Irene", "Hugo", "Nuria", "Óscar", "Sara", "Lucía María", "José Luis", "María José", "Adrián"]
SURNAMES = ["Pérez", "Gil", "Muñoz", "Fernández", "Álvarez", "Castro", "Martínez", "Suárez", "Alonso", "Prieto",
            "Llano", "Noval", "Rubiera", "Fueyo", "Prendes", "Menéndez", "Rodríguez", "Díaz", "García", "Iglesias"]
CITIES = [("Oviedo", "330"), ("Gijón", "332"), ("Avilés", "334"), ("Alicante", "030"), ("Barcelona", "080"),
          ("Almería", "040"), ("León", "240"), ("Madrid", "280")]
STREETS = ["C/ Uría", "Av. Galicia", "Calle Mayor", "Plaza de España", "C/ Jovellanos", "Av. Constitución"]
ALLERGIES = ["Penicilina", "Látex", "Marisco", "Aspirina", "Polen", "Ibuprofeno"]
BLOOD = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

TARGETS = ["paciente.id", "paciente.dni", "paciente.nombre", "paciente.apellidos", "paciente.fecha_nacimiento",
           "paciente.sexo", "paciente.telefono", "direccion.calle", "direccion.ciudad", "direccion.codigo_postal",
           "datos_clinicos.grupo_sanguineo", "datos_clinicos.peso_kg", "datos_clinicos.altura_cm",
           "datos_clinicos.alergia", "datos_clinicos.medico_responsable"]
REQUIRED = {"paciente.id", "paciente.nombre", "paciente.apellidos", "paciente.fecha_nacimiento", "paciente.sexo"}

# Header names a real export might use, by language. "cryptic" is the short codes of old systems.
HEADERS = {
    "paciente.id": {"es": ["NHC", "Nº historia", "Número de historia clínica", "ID paciente", "Historia"],
                    "en": ["Patient ID", "MRN", "Medical record number"], "cryptic": ["NHC", "NUMHC", "COD_PAC"]},
    "paciente.dni": {"es": ["DNI", "DNI/NIE", "Documento identidad", "NIF"], "en": ["National ID", "ID document"],
                     "cryptic": ["DNI", "NIF"]},
    "paciente.nombre": {"es": ["Nombre", "Nombre de pila"], "en": ["First name", "Given name"],
                        "cryptic": ["NOM", "NOMBRE"]},
    "paciente.apellidos": {"es": ["Apellidos"], "en": ["Last name", "Surname", "Family name"],
                           "cryptic": ["APELLIDOS", "APES"]},
    "paciente.fecha_nacimiento": {"es": ["Fecha de nacimiento", "Fecha nacimiento", "F. Nac.", "Nacimiento"],
                                  "en": ["DOB", "Date of birth", "Birth date"], "cryptic": ["FNAC", "F_NAC"]},
    "paciente.sexo": {"es": ["Sexo", "Género"], "en": ["Gender", "Sex"], "cryptic": ["SX", "SEXO"]},
    "paciente.telefono": {"es": ["Teléfono", "Móvil", "Teléfono paciente"], "en": ["Mobile", "Phone"],
                          "cryptic": ["TLF", "TEL"]},
    "direccion.calle": {"es": ["Dirección", "Domicilio", "Calle"], "en": ["Address", "Street"],
                        "cryptic": ["DOM", "DIREC"]},
    "direccion.ciudad": {"es": ["Ciudad", "Localidad", "Municipio", "Población"], "en": ["City", "Town"],
                         "cryptic": ["LOC", "POBL"]},
    "direccion.codigo_postal": {"es": ["Código postal", "CP", "C.P."], "en": ["Zip", "Postal code", "Postcode"],
                                "cryptic": ["CP", "CPOSTAL"]},
    "datos_clinicos.grupo_sanguineo": {"es": ["Grupo sanguíneo", "Grupo y Rh"], "en": ["Blood type", "Blood group"],
                                       "cryptic": ["GS", "GRUPO_RH"]},
    "datos_clinicos.peso_kg": {"es": ["Peso", "Peso (kg)"], "en": ["Weight", "Weight (kg)"], "cryptic": ["PESO"]},
    "datos_clinicos.altura_cm": {"es": ["Talla", "Talla (cm)", "Altura (cm)"], "en": ["Height (cm)", "Height"],
                                 "cryptic": ["TALLA", "ALT"]},
    "datos_clinicos.alergia": {"es": ["Alergias", "Alergias conocidas"], "en": ["Allergies"],
                               "cryptic": ["ALERG", "ALERGIAS"]},
    "datos_clinicos.medico_responsable": {"es": ["Médico responsable", "Facultativo", "Médico"],
                                          "en": ["Attending physician", "GP", "Doctor"], "cryptic": ["MED", "FACUL"]},
}
GRAMS = {"es": ["Peso (g)", "Peso en gramos"], "en": ["Weight (g)"], "cryptic": ["PESO_G"]}
METRES = {"es": ["Talla (m)", "Altura (m)"], "en": ["Height (m)"], "cryptic": ["TALLA_M"]}
SPLIT = {"es": [("Primer apellido", "Segundo apellido"), ("Apellido 1", "Apellido 2")],
         "en": [("Surname 1", "Surname 2")], "cryptic": [("APE1", "APE2"), ("AP1", "AP2")]}
FULL = {"es": ["Nombre y apellidos", "Nombre completo"], "en": ["Full name", "Patient name"],
        "cryptic": ["NOMBRE_COMPLETO", "NOMAPE"]}
SECTION = {"paciente": "Paciente", "direccion": "Dirección", "datos_clinicos": "Clínica"}
# Columns that look like a target but belong to something else.
DISTRACTORS = {
    "contact_phone": {"es": "Teléfono familiar", "en": "Next of kin phone", "cryptic": "TLF_FAM"},
    "contact_name": {"es": "Persona de contacto", "en": "Contact name", "cryptic": "CONTACTO"},
    "admission": {"es": "Fecha ingreso", "en": "Admission date", "cryptic": "FING"},
    "room": {"es": "Nº habitación", "en": "Room", "cryptic": "HAB"},
    "notes": {"es": "Observaciones", "en": "Notes", "cryptic": "OBS"},
    "free": {"es": "Campo libre 1", "en": "Custom 1", "cryptic": "CL1"},
}
SEX = [{"male": "male", "female": "female"}, {"male": "Hombre", "female": "Mujer"}, {"male": "H", "female": "M"},
       {"male": "V", "female": "M"}, {"male": "Male", "female": "Female"}, {"male": "M", "female": "F"}]
DATES = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y%m%d"]


def people(r, n: int) -> list[dict]:
    out, ids = [], set()
    id_style = r.choice(["NHC-{:05d}", "MRN{:06d}", "{:05d}", "HC{:07d}"])
    for _ in range(n):
        num = r.randrange(10000, 99999)
        while num in ids:
            num = r.randrange(10000, 99999)
        ids.add(num)
        given = r.choice(GIVEN)
        s1, s2 = r.sample(SURNAMES, 2)
        city, prefix = r.choice(CITIES)
        dni = r.randrange(10_000_000, 99_999_999)
        weight = round(r.uniform(45, 110), 1)
        out.append({
            "paciente.id": id_style.format(num),
            "paciente.dni": f"{dni}{DNI_LETTERS[dni % 23]}" if r.random() < 0.85 else None,
            "paciente.nombre": given, "paciente.apellidos": f"{s1} {s2}", "_s1": s1, "_s2": s2,
            "paciente.fecha_nacimiento": dt.date(r.randrange(1935, 2010), r.randrange(1, 13), r.randrange(1, 29)),
            "paciente.sexo": r.choice(["male", "female"]),
            "paciente.telefono": f"+346{r.randrange(10_000_000, 99_999_999)}" if r.random() < 0.9 else None,
            "direccion.calle": f"{r.choice(STREETS)} {r.randrange(1, 80)}", "direccion.ciudad": city,
            "direccion.codigo_postal": f"{prefix}{r.randrange(1, 20):02d}",
            "datos_clinicos.grupo_sanguineo": r.choice(BLOOD) if r.random() < 0.8 else None,
            "datos_clinicos.peso_kg": int(weight) if weight.is_integer() else weight,
            "datos_clinicos.altura_cm": r.randrange(150, 196),
            "datos_clinicos.alergia": "; ".join(r.sample(ALLERGIES, r.choice([0, 0, 1, 1, 2]))) or None,
            "datos_clinicos.medico_responsable": f"{r.choice(GIVEN[:16])} {r.choice(SURNAMES)}",
        })
    return out


def canonical(p: dict) -> dict:
    """The correct output values of one person (the destination's own formats)."""
    out = {t: p[t] for t in TARGETS}
    out["paciente.fecha_nacimiento"] = p["paciente.fecha_nacimiento"].isoformat()
    return out


def _style(r, fmt: str) -> dict:
    return {
        "lang": r.choice(["es", "es", "en", "cryptic"]),
        "prefix": fmt in ("csv", "xlsx") and r.random() < 0.25,
        "date": r.choice(DATES) if fmt != "json" else r.choice(["%Y-%m-%d", "%d/%m/%Y"]),
        "native_date": fmt == "xlsx" and r.random() < 0.5,
        "sex": r.randrange(len(SEX)),
        "upper": r.random() < 0.3,
        "phone": r.choice(["{}", "{} {} {} {}", "+34{}", "0034{}", "+34 {}"]),
        "grams": r.random() < 0.2, "metres": r.random() < 0.25,
        "decimal_comma": fmt == "csv" and r.random() < 0.5,
        "cp_lost_zero": fmt in ("csv", "xlsx", "json") and r.random() < 0.4,
        "blood": r.choice(["plain", "plain", "rh", "pos"]),
        "names": r.choice(["one", "one", "split", "full"]),
        "dropped": [],
        "distractors": [],
    }


def _phone(s: str, style: str) -> str:
    d = s[3:]
    if style == "{} {} {} {}":
        return f"{d[:3]} {d[3:5]} {d[5:7]} {d[7:]}"
    if style == "+34 {}":
        return f"+34 {d[:3]} {d[3:6]} {d[6:]}"
    return style.format(d)


def _blood(b: str, style: str) -> str:
    g, sign = b[:-1], b[-1]
    if style == "rh":
        return f"{g} Rh{sign}"
    if style == "pos":
        return f"{g} {'POS' if sign == '+' else 'NEG'}"
    return b


def _number(v, comma: bool, native: bool):
    if v is None:
        return None
    if native:
        return v
    s = str(v)
    return s.replace(".", ",") if comma else s


def table(r, ps: list[dict], fmt: str, style: dict) -> tuple[list[Column], dict[str, list[str]]]:
    """The columns of a table export and which headers hold each target."""
    lang, native = style["lang"], fmt in ("xlsx", "json")

    def head(pool: dict):
        options = pool[lang] if r.random() < 0.8 else pool[r.choice(list(pool))]
        return r.choice(options)

    def named(target: str, header: str) -> tuple[str, str]:
        section = target.split(".")[0]
        if style["prefix"]:
            return f"{SECTION[section]} / {header}", section
        return header, section

    cols: list[Column] = []
    truth: dict[str, list[str]] = {t: [] for t in TARGETS}
    used: set[str] = set()

    def add(targets: list[str], header: str, values: list, section: str = "") -> None:
        while header in used:
            header += " 2"
        used.add(header)
        cols.append(Column(header, values, section))
        if any(v is not None for v in values):
            for t in targets:
                truth[t].append(header)

    for t in TARGETS:
        if t not in REQUIRED and r.random() < 0.15:
            style["dropped"].append(t)
            continue
        if t == "paciente.apellidos" and style["names"] == "full":
            continue
        values = [p[t] for p in ps]
        if t == "paciente.nombre" and style["names"] == "full":
            h, sec = named(t, head(FULL))
            full = [f"{p['paciente.nombre']} {p['paciente.apellidos']}" for p in ps]
            add([t, "paciente.apellidos"], h, [v.upper() if style["upper"] else v for v in full], sec)
            continue
        if t == "paciente.apellidos" and style["names"] == "split":
            a, b = r.choice(SPLIT[lang] if r.random() < 0.8 else SPLIT["es"])
            for h, k in ((a, "_s1"), (b, "_s2")):
                h, sec = named(t, h)
                add([t], h, [p[k].upper() if style["upper"] else p[k] for p in ps], sec)
            continue
        pool = HEADERS[t]
        if t == "datos_clinicos.peso_kg" and style["grams"]:
            pool, values = GRAMS, [round(v * 1000) for v in values]
        if t == "datos_clinicos.altura_cm" and style["metres"]:
            pool, values = METRES, [round(v / 100, 2) for v in values]
        if t in ("paciente.nombre", "paciente.apellidos", "datos_clinicos.medico_responsable") and style["upper"]:
            values = [v.upper() for v in values]
        if t == "paciente.fecha_nacimiento":
            values = values if style["native_date"] else [v.strftime(style["date"]) for v in values]
        if t == "paciente.sexo":
            values = [SEX[style["sex"]][v] for v in values]
        if t == "paciente.telefono":
            values = [_phone(v, style["phone"]) if v else None for v in values]
        if t == "direccion.codigo_postal" and style["cp_lost_zero"]:
            values = [int(v) if native else str(int(v)) for v in values]
        if t == "datos_clinicos.grupo_sanguineo":
            values = [_blood(v, style["blood"]) if v else None for v in values]
        if t in ("datos_clinicos.peso_kg", "datos_clinicos.altura_cm"):
            values = [_number(v, style["decimal_comma"], native) for v in values]
        h, sec = named(t, head(pool))
        add([t], h, values, sec)

    for kind in r.sample(sorted(DISTRACTORS), r.randrange(0, 4)):
        style["distractors"].append(kind)
        h = DISTRACTORS[kind][lang]
        if kind == "contact_phone":
            vals = [f"6{r.randrange(10_000_000, 99_999_999)}" for _ in ps]
        elif kind == "contact_name":
            vals = [f"{r.choice(GIVEN)} {r.choice(SURNAMES)}" for _ in ps]
        elif kind == "admission":
            day = [dt.date(2026, r.randrange(1, 13), r.randrange(1, 29)) for _ in ps]
            vals = day if style["native_date"] else [d.strftime(style["date"]) for d in day]
        elif kind == "room":
            vals = [r.randrange(100, 450) if native else str(r.randrange(100, 450)) for _ in ps]
        elif kind == "notes":
            vals = [r.choice(["", "Control en 3 meses", "Acude acompañado", "Revisar analítica"]) or None for _ in ps]
        else:
            vals = [r.choice(["A", "B", "C", None]) for _ in ps]
        add([], h, vals)
    r.shuffle(cols)
    key = next(c for c in cols if c.header in truth["paciente.id"])     # the key first (XML may make it an attribute)
    cols.remove(key)
    return [key] + cols, truth


# --- HL7 v2 and FHIR: the field positions are the standard's, the messiness is in the values ----------

def hl7(r, ps: list[dict], style: dict) -> tuple[bytes, dict[str, list[str]]]:
    v25 = r.random() < 0.5
    with_dni = any(p["paciente.dni"] for p in ps)
    msgs = []
    for i, p in enumerate(ps, 1):
        up = (lambda s: s.upper()) if style["upper"] else (lambda s: s)
        pid3 = f"{p['paciente.id']}^^^HOSP^MR"
        if v25 and p["paciente.dni"]:
            pid3 += f"~{p['paciente.dni']}^^^MIR^NI"
        seg = [f"MSH|^~\\&|HIS|HOSP|MB|DEST|20260401{i:02d}0000||ADT^A01|MSG{i:04d}|P|{'2.5' if v25 else '2.3'}",
               "PID|1||{}||{}^{}||{}|{}|||{}^^{}^^{}^ES||{}||||||{}".format(
                   pid3, up(p["paciente.apellidos"]), up(p["paciente.nombre"]),
                   p["paciente.fecha_nacimiento"].strftime("%Y%m%d"), "M" if p["paciente.sexo"] == "male" else "F",
                   p["direccion.calle"], p["direccion.ciudad"], p["direccion.codigo_postal"],
                   _phone(p["paciente.telefono"], style["phone"]) if p["paciente.telefono"] else "",
                   "" if v25 else p["paciente.dni"] or ""),
               "PV1|1|I|MED^{}^1||||D0{}^{}^{}".format(r.randrange(100, 400), r.randrange(100, 999),
                                                       *[up(x) for x in reversed(p["datos_clinicos.medico_responsable"].split(" ", 1))])]
        for k, a in enumerate((p["datos_clinicos.alergia"] or "").split("; ") if p["datos_clinicos.alergia"] else [], 1):
            seg.append(f"AL1|{k}|DA|{a[:3].upper()}^{a}|SV")
        seg.append(f"OBX|1|NM|29463-7^Peso corporal^LN||{p['datos_clinicos.peso_kg']}|kg|||||F")
        seg.append(f"OBX|2|NM|8302-2^Talla^LN||{p['datos_clinicos.altura_cm']}|cm|||||F")
        if p["datos_clinicos.grupo_sanguineo"]:
            seg.append(f"ZPA|1|{p['datos_clinicos.grupo_sanguineo']}")
        msgs.append(seg)
    sep = r.choice(["\r", "\r\n", "\n"])
    data = "".join(sep.join(m) + sep for m in msgs).encode("utf-8")
    style.update(version="2.5" if v25 else "2.3", segment_separator=repr(sep))
    pid3 = (lambda kind: f"PID-3.1 [PID-3.5={kind}]") if v25 and with_dni else (lambda kind: "PID-3.1")
    truth = {
        "paciente.id": [pid3("MR")], "paciente.dni": [pid3("NI") if v25 else "PID-19"] if with_dni else [],
        "paciente.nombre": ["PID-5.2"], "paciente.apellidos": ["PID-5.1"], "paciente.fecha_nacimiento": ["PID-7"],
        "paciente.sexo": ["PID-8"], "paciente.telefono": ["PID-13"] if any(p["paciente.telefono"] for p in ps) else [],
        "direccion.calle": ["PID-11.1"], "direccion.ciudad": ["PID-11.3"], "direccion.codigo_postal": ["PID-11.5"],
        "datos_clinicos.grupo_sanguineo": ["ZPA-2"] if any(p["datos_clinicos.grupo_sanguineo"] for p in ps) else [],
        "datos_clinicos.peso_kg": ["OBX-5 [OBX-3.1=29463-7]"], "datos_clinicos.altura_cm": ["OBX-5 [OBX-3.1=8302-2]"],
        "datos_clinicos.alergia": ["AL1-3.2"] if any(p["datos_clinicos.alergia"] for p in ps) else [],
        "datos_clinicos.medico_responsable": ["PV1-7.3", "PV1-7.2"],
    }
    return data, truth


def fhir(r, ps: list[dict], style: dict) -> tuple[bytes, dict[str, list[str]]]:
    base = "http://example.org/fhir/StructureDefinition/"
    entries = []
    for i, p in enumerate(ps, 1):
        pid = f"p{i}"
        res = {"resourceType": "Patient", "id": pid,
               "identifier": [{"system": "urn:hospital:nhc", "value": p["paciente.id"]}]
               + ([{"system": "urn:es:dni", "value": p["paciente.dni"]}] if p["paciente.dni"] else []),
               "name": [{"use": "official", "family": p["paciente.apellidos"], "given": [p["paciente.nombre"]]}],
               "gender": p["paciente.sexo"], "birthDate": p["paciente.fecha_nacimiento"].isoformat(),
               "address": [{"line": [p["direccion.calle"]], "city": p["direccion.ciudad"],
                            "postalCode": p["direccion.codigo_postal"], "country": "ES"}],
               "generalPractitioner": [{"display": p["datos_clinicos.medico_responsable"]}]}
        if p["paciente.telefono"]:
            res["telecom"] = [{"system": "phone", "value": p["paciente.telefono"]}]
        if p["datos_clinicos.grupo_sanguineo"]:
            res["extension"] = [{"url": base + "grupo-sanguineo", "valueString": p["datos_clinicos.grupo_sanguineo"]}]
        entries.append(res)
        for code, value, unit in (("29463-7", p["datos_clinicos.peso_kg"], "kg"),
                                  ("8302-2", p["datos_clinicos.altura_cm"], "cm")):
            entries.append({"resourceType": "Observation", "id": f"o{i}-{code}", "status": "final",
                            "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
                            "subject": {"reference": f"Patient/{pid}"},
                            "valueQuantity": {"value": value, "unit": unit}})
        for k, a in enumerate((p["datos_clinicos.alergia"] or "").split("; ") if p["datos_clinicos.alergia"] else []):
            entries.append({"resourceType": "AllergyIntolerance", "id": f"a{i}-{k}",
                            "patient": {"reference": f"Patient/{pid}"}, "code": {"text": a}})
    if r.random() < 0.5:
        r.shuffle(entries)
        order = [e["id"] for e in entries if e["resourceType"] == "Patient"]
        for i, p in enumerate(ps, 1):     # several allergies come out in the bundle's order
            mine = [e["code"]["text"] for e in entries if e["resourceType"] == "AllergyIntolerance"
                    and e["patient"]["reference"] == f"Patient/p{i}"]
            p["datos_clinicos.alergia"] = "; ".join(mine) or None
        ps[:] = [ps[int(pid[1:]) - 1] for pid in order]     # one row per Patient, in the bundle's order
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": e} for e in entries]}
    data = json.dumps(bundle, ensure_ascii=False, indent=r.choice([None, 2])).encode("utf-8")
    obs = "Observation.valueQuantity.value [Observation.code.coding.code={}]"
    truth = {
        "paciente.id": ["identifier[nhc].value"],
        "paciente.dni": ["identifier[dni].value"] if any(p["paciente.dni"] for p in ps) else [],
        "paciente.nombre": ["name[official].given"], "paciente.apellidos": ["name[official].family"],
        "paciente.fecha_nacimiento": ["birthDate"], "paciente.sexo": ["gender"],
        "paciente.telefono": ["telecom[phone].value"] if any(p["paciente.telefono"] for p in ps) else [],
        "direccion.calle": ["address.line"], "direccion.ciudad": ["address.city"],
        "direccion.codigo_postal": ["address.postalCode"],
        "datos_clinicos.grupo_sanguineo": ["extension[grupo-sanguineo]"]
        if any(p["datos_clinicos.grupo_sanguineo"] for p in ps) else [],
        "datos_clinicos.peso_kg": [obs.format("29463-7")], "datos_clinicos.altura_cm": [obs.format("8302-2")],
        "datos_clinicos.alergia": ["AllergyIntolerance.code.text"] if any(p["datos_clinicos.alergia"] for p in ps) else [],
        "datos_clinicos.medico_responsable": ["generalPractitioner.display"],
    }
    return data, truth


def generate(r, fmt: str, seed: int) -> Case:
    ps = people(r, r.randrange(3, 9))
    style = _style(r, fmt)
    title = r.choice(["LISTADO PACIENTES - URGENCIAS", "Exportación pacientes", "Informe de altas"])
    if fmt == "hl7":
        data, truth = hl7(r, ps, style)
        name = f"pacientes_{seed}.hl7"
        dropped = set()
    elif fmt == "fhir":
        data, truth = fhir(r, ps, style)
        name = f"pacientes_{seed}.json"
        dropped = set()
    else:
        cols, truth = table(r, ps, fmt, style)
        if fmt == "csv":
            data, more, names = csv_file(cols, r, title)
        elif fmt == "xlsx":
            data, more, names = xlsx_file(cols, r, title)
        elif fmt == "json":
            data, more, names = json_file(cols, r, title)
        else:
            data, more, names = xml_file(cols, r, title, "pacientes", "paciente")
        style.update(more)
        truth = {t: [names[h] for h in hs] for t, hs in truth.items()}
        name = f"pacientes_{seed}.{fmt}"
        dropped = set(style["dropped"])
    values = []
    for p in ps:
        v = canonical(p)
        for t in TARGETS:
            if t in dropped or not truth[t]:
                v[t] = None
        values.append(v)
    return Case("pacientes", fmt, seed, name, data, DESTINATION, truth, values, style)
