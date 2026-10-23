"""Phase 5: a generic core, clinical knowledge only in its pack, and a proposal with no pack at all."""

import re
from pathlib import Path

import pytest

from multibridge import formats, packs
from multibridge.expected import Expected
from multibridge.matcher import propose
from multibridge.parsers import parse_bytes
from multibridge.profile import profile_dataset
from multibridge.records import to_rows

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "multibridge"
# Plug-ins may know their domain or format; nothing else may.
ALLOWED = ("packs", "formats", "parsers/hl7v2.py", "parsers/fhir.py")
CLINICAL = re.compile(r"patient|paciente|hospital|hl7|fhir|loinc|icd|pid-|obx|clinic|clínic|m[eé]dic|diagn|"
                      r"observation|practitioner|nhc", re.I)

# A small shop export, nothing clinical: dd/mm/yyyy dates, decimal commas, a status code.
ORDERS = """Tienda Centro - pedidos
Numero;Fecha pedido;Cliente;Email;Importe;Estado
P-1001;05/03/2026;Ana Ruiz;ana@example.com;12,50;P
P-1002;06/03/2026;Luis Gil;luis@example.com;7,25;X
P-1003;07/03/2026;Eva Sanz;eva@example.com;30,00;P
P-1004;07/03/2026;Ana Ruiz;ana@example.com;5,10;P
""".encode("utf-8")
ORDER_EXAMPLE = {"pedido": {"numero": "P-1", "fecha_pedido": "2026-01-01", "cliente": "Nombre Apellido",
                            "email": "a@b.es", "importe": 9.99, "estado": "pagado", "descuento": 0.5}}
ORDER_RULES = {"pedido.numero": {"required": True}, "pedido.estado": {"enum": ["pagado", "cancelado"]}}


def test_core_has_no_clinical_terms():
    hits = []
    for p in sorted(CORE.rglob("*.py")):
        rel = p.relative_to(CORE).as_posix()
        if rel.startswith(ALLOWED):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if CLINICAL.search(line):
                hits.append(f"{rel}:{n}: {line.strip()}")
    assert hits == []


def test_destination_declares_its_pack():
    assert Expected.load(ROOT / "expected" / "cdss_paciente.example.json").pack == "clinical"
    plain = Expected.from_example(ORDER_EXAMPLE, name="pedido", rules=ORDER_RULES)
    assert plain.pack is None and all(t.concept is None for t in plain.targets)
    with pytest.raises(ValueError, match="pack desconocido"):
        Expected.from_example(ORDER_EXAMPLE, name="pedido", rules={"$pack": "nope"})


def test_pack_is_not_part_of_the_destination_id():
    rules = {**ORDER_RULES, "$pack": "clinical"}
    assert Expected.from_example(ORDER_EXAMPLE, "pedido", rules).id == \
        Expected.from_example(ORDER_EXAMPLE, "pedido", ORDER_RULES).id


def test_no_pack_proposal_uses_names_types_and_formats():
    rows = to_rows(parse_bytes(ORDERS, "pedidos.csv"))
    fields = propose(rows, Expected.from_example(ORDER_EXAMPLE, name="pedido", rules=ORDER_RULES))["fields"]
    for target, column in [("pedido.numero", "Numero"), ("pedido.fecha_pedido", "Fecha pedido"),
                           ("pedido.cliente", "Cliente"), ("pedido.email", "Email"), ("pedido.importe", "Importe")]:
        assert fields[target]["status"] == "mapped" and fields[target]["from"] == [column], target
    assert {"op": "date", "from": "%d/%m/%Y"} in fields["pedido.fecha_pedido"]["transforms"]
    assert {"op": "number", "decimal": ","} in fields["pedido.importe"]["transforms"]
    # No pack knows what P/X mean: a person translates them, nothing is guessed.
    assert fields["pedido.estado"]["status"] == "pending"
    assert any("sin traducción" in i for i in fields["pedido.estado"]["issues"])
    assert fields["pedido.descuento"]["status"] == "no_data"


def test_profiling_without_packs_still_finds_personal_data():
    ds = profile_dataset(parse_bytes(ORDERS, "pedidos.csv", profile=False), packs=[])
    by = {f.path: f for f in ds.fields}
    assert by["Email"].sensitive and by["Email"].sensitive_reason == "contacto"
    # "Cliente" isn't a name hint, but its values are people's names: never shown to the AI as categories
    assert by["Cliente"].sensitive and by["Cliente"].sensitive_reason == "valores con formato de nombre de persona"
    assert by["Cliente"].categories is None
    assert not by["Importe"].sensitive and by["Importe"].dtype == "decimal"
    assert all(f.kind != packs.get("clinical").concept_kind for f in ds.fields)


def test_core_detects_iban_and_special_categories():
    ds = profile_dataset(parse_bytes(
        "Cuenta;Religión;Ref\nES91 2100 0418 4502 0005 1332;x;A1\nES7921000813610123456789;y;A2\n".encode(),
        "x.csv", profile=False), packs=[])
    by = {f.path: f for f in ds.fields}
    assert by["Cuenta"].sensitive_reason == "valores con formato de IBAN"
    assert by["Religión"].sensitive_reason == "categoría especial (art. 9 RGPD)"
    assert not by["Ref"].sensitive


def test_clinical_pack_adds_its_personal_data_hints():
    ds = parse_bytes("NHC;Peso\n30001;70\n30002;80\n".encode(), "x.csv", profile=False)
    assert not profile_dataset(ds, packs=[]).get(ds.entities()[0], "NHC").sensitive
    assert profile_dataset(ds, packs=[packs.get("clinical")]).get(ds.entities()[0], "NHC").sensitive_reason \
        == "identificador del paciente"


def test_format_registry():
    assert formats.detect(b"MSH|^~\\&|A", "m.txt").name == "hl7v2"
    assert formats.detect(b"PK\x03\x04", "x.bin").name == "excel"
    assert formats.detect(b'[{"a": 1}]', "x.data").name == "json"
    assert formats.detect(b"a;b\n1;2", "x.csv").name == "csv"
    with pytest.raises(formats.UnsupportedFormat):
        formats.detect(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "old.xls")
    assert formats.detect(b"<a><b>1</b></a>", "x.data").name == "xml"
    json_ = formats.get("json")
    flat = Expected.from_example({"a": "x", "b": 1}, name="ab")
    out = json_.write([{"a": "é", "b": 1}], flat)
    assert out == '[\n  {\n    "a": "é",\n    "b": 1\n  }\n]\n'.encode("utf-8") and json_.check(out) == []
    assert json_.check(b"{oops") and json_.check(b'{"a": 1}')
    with pytest.raises(NotImplementedError):
        formats.get("hl7v2").write([{}], flat)
