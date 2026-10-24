"""Invented order lines for examples/destinos/pedido_json.example.json (no domain pack).

One row per order line; the destination groups them by order number. Every company, tax number
and address is made up (docs/COMPLIANCE.md C1).
"""

from __future__ import annotations

import datetime as dt

from . import ROOT, Case
from .render import Column, csv_file, json_file, xlsx_file, xml_file

FORMATS = ("csv", "xlsx", "json", "xml")
DESTINATION = ROOT / "examples" / "destinos" / "pedido_json.example.json"

COMPANIES = ["Ferretería Norte SL", "Talleres Sela SA", "Construcciones Prieto SL", "Suministros Nalón SL",
             "Maderas del Caudal SA", "Electricidad Riera SL", "Fontanería Llanes SL", "Pinturas Deva SA"]
CITIES = ["Oviedo", "Gijón", "Avilés", "Mieres", "Langreo", "Llanes", "Cangas", "Siero"]
ITEMS = [("T-440", "Tornillo 4x40 (caja 100)"), ("B-12", "Broca HSS 12 mm"), ("L-01", "Llave inglesa 10\""),
         ("C-25", "Cemento cola 25 kg"), ("G-02", "Guantes de nitrilo (par)"), ("P-10", "Paleta de albañil"),
         ("M-05", "Martillo de carpintero"), ("S-30", "Silicona blanca 300 ml"), ("K-07", "Cinta métrica 5 m")]

LINE = "lineas[]."
TARGETS = ["numero", "fecha", "cliente.nombre", "cliente.nif", "cliente.email", "entrega.ciudad",
           LINE + "referencia", LINE + "descripcion", LINE + "cantidad", LINE + "precio_unitario",
           LINE + "descuento_pct"]
REQUIRED = {"numero", LINE + "referencia"}
HEADERS = {
    "numero": {"es": ["Num. pedido", "Nº pedido", "Número de pedido", "Pedido"], "en": ["Order number", "Order no."],
               "cryptic": ["NUMPED", "N_PED"]},
    "fecha": {"es": ["Fecha pedido", "Fecha", "F. pedido"], "en": ["Order date", "Date"], "cryptic": ["FPED", "FEC"]},
    "cliente.nombre": {"es": ["Cliente", "Nombre cliente", "Razón social"], "en": ["Customer", "Customer name"],
                       "cryptic": ["CLI", "NOMCLI"]},
    "cliente.nif": {"es": ["NIF cliente", "NIF", "CIF"], "en": ["Customer tax ID", "VAT number"],
                    "cryptic": ["NIF", "CIF_CLI"]},
    "cliente.email": {"es": ["E-mail", "Email cliente", "Correo electrónico"], "en": ["Email", "Customer email"],
                      "cryptic": ["EMAIL", "MAIL"]},
    "entrega.ciudad": {"es": ["Ciudad entrega", "Localidad de entrega"], "en": ["Delivery city", "Ship to city"],
                       "cryptic": ["CIU_ENT", "LOCENT"]},
    LINE + "referencia": {"es": ["Ref.", "Referencia", "Código artículo"], "en": ["Item code", "SKU", "Reference"],
                          "cryptic": ["REF", "CODART"]},
    LINE + "descripcion": {"es": ["Descripción artículo", "Descripción", "Artículo"], "en": ["Description", "Item"],
                           "cryptic": ["DESC", "DESCART"]},
    LINE + "cantidad": {"es": ["Cantidad (uds)", "Cantidad", "Uds."], "en": ["Quantity", "Qty"],
                        "cryptic": ["CANT", "UDS"]},
    LINE + "precio_unitario": {"es": ["Precio unitario €", "Precio unitario", "P. unit."],
                               "en": ["Unit price", "Price per unit"], "cryptic": ["PRECIO", "PUNIT"]},
    LINE + "descuento_pct": {"es": ["% Dto.", "Descuento %", "Dto."], "en": ["Discount %", "Discount"],
                             "cryptic": ["DTO", "PDTO"]},
}
SECTION = {"numero": "pedido", "fecha": "pedido", "cliente": "cliente", "entrega": "entrega", "lineas[]": "linea"}
DISTRACTORS = {
    "rep": {"es": "Comercial", "en": "Sales rep", "cryptic": "COMERC"},
    "note": {"es": "Nota interna", "en": "Internal note", "cryptic": "NOTA"},
    "total": {"es": "Importe línea", "en": "Line total", "cryptic": "IMPLIN"},
    "delivery": {"es": "Fecha entrega", "en": "Delivery date", "cryptic": "FENT"},
    "phone": {"es": "Teléfono", "en": "Phone", "cryptic": "TLF"},
    "store": {"es": "Almacén", "en": "Warehouse", "cryptic": "ALM"},
}
DATES = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]


def lines(r) -> list[dict]:
    out = []
    style = r.choice(["PED-{}", "{}", "2026/{:04d}"])
    for k in range(r.randrange(2, 6)):
        num = style.format(1000 + 37 * k + r.randrange(0, 30))
        company = r.choice(COMPANIES)
        head = {"numero": num, "fecha": dt.date(2026, r.randrange(1, 13), r.randrange(1, 29)), "cliente.nombre": company,
                "cliente.nif": f"{r.choice('AB')}{r.randrange(10_000_000, 99_999_999)}",
                "cliente.email": "compras@" + company.split()[0].lower().replace("í", "i").replace("é", "e") + ".example",
                "entrega.ciudad": r.choice(CITIES)}
        for ref, desc in r.sample(ITEMS, r.randrange(1, 5)):
            out.append({**head, LINE + "referencia": ref, LINE + "descripcion": desc,
                        LINE + "cantidad": r.randrange(1, 60), LINE + "precio_unitario": round(r.uniform(0.5, 40), 2),
                        LINE + "descuento_pct": r.choice([0, 0, 5, 10, 15])})
    r.shuffle(out)
    if r.random() < 0.3:     # one line without its order number: the engine sets it aside
        out[-1] = {**out[-1], "numero": None}
    return out


def generate(r, fmt: str, seed: int) -> Case:
    ls = lines(r)
    lang, native = r.choice(["es", "es", "en", "cryptic"]), fmt in ("xlsx", "json")
    style = {"lang": lang, "date": r.choice(DATES), "native_date": fmt == "xlsx" and r.random() < 0.5,
             "decimal_comma": fmt == "csv" and r.random() < 0.6, "dropped": [], "distractors": []}
    cols: list[Column] = []
    truth: dict[str, list[str]] = {t: [] for t in TARGETS}
    used: set[str] = set()

    def add(target: str | None, header: str, values: list, section: str = "") -> None:
        while header in used:
            header += " 2"
        used.add(header)
        cols.append(Column(header, values, section))
        if target and any(v is not None for v in values):
            truth[target].append(header)

    for t in TARGETS:
        if t not in REQUIRED and r.random() < 0.12:
            style["dropped"].append(t)
            continue
        pool = HEADERS[t]
        header = r.choice(pool[lang] if r.random() < 0.8 else pool[r.choice(list(pool))])
        values = [line[t] for line in ls]
        if t == "fecha":
            values = values if style["native_date"] else [v.strftime(style["date"]) for v in values]
        elif t.endswith(("cantidad", "precio_unitario", "descuento_pct")) and not native:
            values = [str(v).replace(".", ",") if style["decimal_comma"] else str(v) for v in values]
        add(t, header, values, SECTION[t.rsplit(".", 1)[0]])
    for kind in r.sample(sorted(DISTRACTORS), r.randrange(0, 4)):
        style["distractors"].append(kind)
        if kind == "rep":
            vals = [r.choice(["Marta", "Iván", "Rosa"]) for _ in ls]
        elif kind == "note":
            vals = [r.choice(["", "urgente", "entregar por la mañana", "cliente preferente"]) or None for _ in ls]
        elif kind == "total":
            totals = [round(x[LINE + "cantidad"] * x[LINE + "precio_unitario"], 2) for x in ls]
            vals = totals if native else [str(v).replace(".", ",") if style["decimal_comma"] else str(v) for v in totals]
        elif kind == "delivery":
            days = [dt.date(2026, r.randrange(1, 13), r.randrange(1, 29)) for _ in ls]
            vals = days if style["native_date"] else [d.strftime(style["date"]) for d in days]
        elif kind == "phone":
            vals = [f"98{r.randrange(1_000_000, 9_999_999)}" for _ in ls]
        else:
            vals = [r.choice(["Central", "Norte", "Puerto"]) for _ in ls]
        add(None, DISTRACTORS[kind][lang], vals)
    r.shuffle(cols)
    key = next(c for c in cols if c.header in truth["numero"])
    cols.remove(key)
    cols = [key] + cols
    title = r.choice(["Distribuciones del Norte - exportación de pedidos", "Pedidos del mes", "Líneas de pedido"])
    if fmt == "csv":
        data, more, names = csv_file(cols, r, title)
    elif fmt == "xlsx":
        data, more, names = xlsx_file(cols, r, title)
    elif fmt == "json":
        data, more, names = json_file(cols, r, title)
    else:
        data, more, names = xml_file(cols, r, title, "pedidos", "linea")
    style.update(more)
    truth = {t: [names[h] for h in hs] for t, hs in truth.items()}
    values = []
    for line in ls:
        v = {t: (line[t] if truth[t] else None) for t in TARGETS}
        if isinstance(v["fecha"], dt.date):
            v["fecha"] = v["fecha"].isoformat()
        values.append(v)
    return Case("pedidos", fmt, seed, f"pedidos_{seed}.{fmt}", data, DESTINATION, truth, values, style)
