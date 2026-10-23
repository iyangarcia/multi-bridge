"""HL7 v2: one record per message, its segments side by side (PID-5.1, PV1-7.2, ZPA-3)."""

from __future__ import annotations

from ..parsers import hl7v2
from . import Format


class Hl7v2(Format):
    name, label, extensions = "hl7v2", "HL7 v2", (".hl7", ".er7")
    joins = True
    timestamp_types = {"TS", "DT", "DTM"}
    coded_types = {"ID", "IS", "PT", "HD", "SI"}   # values come from fixed code tables, not free codes
    # OBX: one segment per observation, OBX-3 says what OBX-5 is.
    keyed_entities = {"OBX": ("OBX-3.1", ["OBX-5", "OBX-6", "OBX-6.1"])}
    unit_of = {"OBX-5": "OBX-6", "OBX-6.1": None}
    # Repeated field -> (segment, component holding its type code, components that carry data).
    # Metadata components (PID-3.4 assigning authority, PID-13.3 equipment type) get no selector: they would
    # inherit the code's meaning ("número de historia clínica") and compete with the real value.
    keyed_fields = {
        "PID-3": ("PID", 5, [1]),                    # CX: ID, by identifier type
        "PID-5": ("PID", 7, [1, 2, 3]),              # XPN: family, given, second given, by name type
        "PID-11": ("PID", 7, [1, 2, 3, 4, 5, 6]),    # XAD: street ... country, by address type
        "PID-13": ("PID", 2, [1, 4, 7]),             # XTN: number, email, local number, by use
        "NK1-2": ("NK1", 7, [1, 2, 3]),
    }
    # The HL7 tables those codes come from. Deliberately avoids words of destination concepts
    # ("domicilio" would read as a street, "nombre" as a given name).
    code_meanings = {
        # table 0203, identifier type (CX.5)
        "MR": "número de historia clínica", "NI": "DNI", "NNESP": "DNI", "PI": "identificador interno",
        "SS": "número de la seguridad social", "PPN": "pasaporte", "JHN": "tarjeta sanitaria",
        "DL": "permiso de conducir",
        # table 0200, name type (XPN.7)
        "L": "legal", "N": "apodo", "A": "alias", "M": "de soltera", "D": "para mostrar",
        # table 0201, telecom use (XTN.2)
        "PRN": "principal", "ORN": "otro", "WPN": "trabajo", "VHN": "vacaciones", "ASN": "contestador",
        "EMR": "emergencia", "NET": "correo electrónico", "BPN": "busca",
        # table 0190, address type (XAD.7)
        "H": "casa", "B": "trabajo", "C": "temporal", "P": "permanente", "BDL": "lugar de nacimiento",
    }

    def sniff(self, data, name):
        # "MSH|^~\&|": the field separator, 4 encoding characters (5 since v2.7) and the separator again.
        # Not just "MSH": a CSV whose first header is "MSH-3" starts the same way.
        head = data[:64].lstrip(b"\xef\xbb\xbf\x0b \r\n\t")
        sep = head[3:4]
        return super().sniff(data, name) or (
            head[:3] == b"MSH" and len(sep) == 1 and not sep.isalnum() and sep not in b" \r\n"
            and sep in (head[8:9], head[9:10]) and not any(chr(c).isalnum() for c in head[4:8]))

    def read(self, data, name):
        return hl7v2.parse(data, name)

    def root(self, ds):
        return "PID" if "PID" in ds.tables else super().root(ds)

    def linked(self, ds, root, rec):
        return {e: [r for r in recs if r.get("_message") == rec.get("_message")]
                for e, recs in ds.tables.items() if e != root}

    def column(self, ds, f, root):
        return f.path   # HL7 paths are already unique across segments


HL7V2 = Hl7v2()
