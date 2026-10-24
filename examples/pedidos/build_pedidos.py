"""Build the phase 8 dataset: order lines of a (made-up) wholesaler, messy like the hard set.

    .venv/Scripts/python examples/pedidos/build_pedidos.py

Nothing clinical and no domain pack: the proposer has only names, profiles and the AI.
Every company, tax number and address is invented (docs/COMPLIANCE.md C1).

    pedidos_lineas.csv    one row per order line: a title line, odd headers, three date shapes,
                          decimal commas, an empty line, a total line, two custom columns
                          ("Comercial", "Nota interna") and one line without an order number
    answers.json          the correct plan per destination and the correct output (an item per order)

The destinations are in examples/destinos/: pedido_json.example.json and pedido_xml.example.xml,
each with a rules file that groups the lines by order number ("$group_by").
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

HEADER = ["Num. pedido", "Fecha pedido", "Cliente", "NIF cliente", "E-mail", "Ciudad entrega", "Ref.",
          "Descripción artículo", "Cantidad (uds)", "Precio unitario €", "% Dto.", "Comercial", "Nota interna"]
LINES = [
    ["PED-1001", "15/01/2026", "Ferretería Norte SL", "B00000001", "compras@ferreteria-norte.example", "Oviedo",
     "T-440", "Tornillo 4x40 (caja 100)", "3", "4,95", "0", "Marta", ""],
    ["PED-1001", "15/01/2026", "Ferretería Norte SL", "B00000001", "compras@ferreteria-norte.example", "Oviedo",
     "B-12", "Broca HSS 12 mm", "10", "2,10", "5", "Marta", "cliente preferente"],
    ["PED-1002", "2026-01-16", "Talleres Sela SA", "A00000002", "pedidos@talleres-sela.example", "Gijón",
     "L-01", "Llave inglesa 10\"", "2", "12,50", "0", "Iván", ""],
    ["PED-1003", "17-01-2026", "Construcciones Prieto SL", "B00000003", "obra@prieto.example", "Avilés",
     "C-25", "Cemento cola 25 kg", "40", "6,80", "10", "Marta", "entregar por la mañana"],
    ["PED-1003", "17-01-2026", "Construcciones Prieto SL", "B00000003", "obra@prieto.example", "Avilés",
     "G-02", "Guantes de nitrilo (par)", "50", "0,85", "10", "Marta", ""],
    ["PED-1003", "17-01-2026", "Construcciones Prieto SL", "B00000003", "obra@prieto.example", "Avilés",
     "P-10", "Paleta de albañil", "4", "7,30", "10", "Marta", ""],
    ["", "18/01/2026", "Talleres Sela SA", "A00000002", "pedidos@talleres-sela.example", "Gijón",
     "B-12", "Broca HSS 12 mm", "5", "2,10", "0", "Iván", "sin número: preguntar"],
]


def write_csv() -> None:
    out = ["Distribuciones del Norte - exportación de pedidos (enero 2026)", "", ";".join(HEADER)]
    out += [";".join(line) for line in LINES]
    out += ["", "Total líneas: 7"]
    (HERE / "pedidos_lineas.csv").write_text("\n".join(out) + "\n", encoding="utf-8")


def m(*cols, t=None) -> dict:
    return {"status": "mapped", "from": list(cols), "transforms": t or []}


DATE = {"op": "date", "from": ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]}
NUMBER = {"op": "number"}
DECIMAL = {"op": "number", "decimal": ","}


def plan(root: str, number: str, line: str) -> dict:
    """The correct decisions, for a destination whose order fields sit under `root` and lines under `line`."""
    return {
        f"{root}{number}": m("Num. pedido"),
        f"{root}fecha": m("Fecha pedido", t=[DATE]),
        f"{root}cliente.nombre": m("Cliente"),
        f"{root}cliente.nif": m("NIF cliente"),
        f"{root}cliente.email": m("E-mail"),
        f"{root}entrega.ciudad": m("Ciudad entrega"),
        f"{line}referencia": m("Ref."),
        f"{line}descripcion": m("Descripción artículo"),
        f"{line}cantidad": m("Cantidad (uds)", t=[NUMBER]),
        f"{line}precio_unitario": m("Precio unitario €", t=[DECIMAL]),
        f"{line}descuento_pct": m("% Dto.", t=[NUMBER]),
    }


def orders() -> list[dict]:
    """The correct output, the JSON view: one item per order, its lines nested."""
    out: dict[str, dict] = {}
    dates = {"15/01/2026": "2026-01-15", "2026-01-16": "2026-01-16", "17-01-2026": "2026-01-17"}
    for (num, fecha, cliente, nif, email, ciudad, ref, desc, qty, price, dto, *_rest) in LINES:
        if not num:
            continue
        o = out.setdefault(num, {"numero": num, "fecha": dates[fecha],
                                 "cliente": {"nombre": cliente, "nif": nif, "email": email},
                                 "entrega": {"ciudad": ciudad}, "lineas": []})
        o["lineas"].append({"referencia": ref, "descripcion": desc, "cantidad": int(qty),
                            "precio_unitario": float(price.replace(",", ".")), "descuento_pct": int(dto)})
    return list(out.values())


def xml_view(order: dict) -> dict:
    """The same order in the XML destination's shape (its JSON view: attributes as "@name")."""
    rest = {k: v for k, v in order.items() if k not in ("numero", "lineas")}
    return {"pedido": {"@numero": order["numero"], **rest, "lineas": {"linea": order["lineas"]}}}


def main() -> None:
    write_csv()
    answers = {"pedidos_lineas.csv": {
        "pedido_json": {"plan": plan("", "numero", "lineas[]."), "items": orders(), "rejected_rows": [6]},
        "pedido_xml": {"plan": plan("pedido.", "@numero", "pedido.lineas.linea[]."),
                       "items": [xml_view(o) for o in orders()],
                       "rejected_rows": [6]},
    }}
    (HERE / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("built pedidos_lineas.csv + answers.json")


if __name__ == "__main__":
    main()
