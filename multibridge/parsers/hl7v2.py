"""HL7 v2.x (pipe-delimited ER7), no external dependency.

One table per segment type (MSH, PID, PV1, AL1, DG1, ZPA...). Every record
carries `_message` (MSH-10) so repeated segments can be joined back to their
message. Paths follow the usual notation: PID-5.1 = field 5, component 1.

Handles: custom encoding characters from MSH-2, repetitions (~), components
(^), sub-components (&), escape sequences (\\F\\ \\S\\ \\T\\ \\R\\ \\E\\ \\.br\\ \\Xhh\\),
MLLP framing bytes, \\r / \\n / \\r\\n segment separators, Z-segments.
"""

from __future__ import annotations

import re

from ..model import Dataset, Field
from .text import decode

# HL7 v2.3 definitions for the segments a clinical app usually receives.
# (field, component) -> (description, data type). Component 0 = the whole field.
SPEC: dict[str, dict[tuple[int, int], tuple[str, str | None]]] = {
    "MSH": {
        (3, 0): ("Aplicación emisora", "HD"), (4, 0): ("Centro emisor", "HD"),
        (5, 0): ("Aplicación receptora", "HD"), (6, 0): ("Centro receptor", "HD"),
        (7, 0): ("Fecha/hora del mensaje", "TS"),
        (9, 0): ("Tipo de mensaje", "CM"), (9, 1): ("Tipo de mensaje: código", "ID"), (9, 2): ("Tipo de mensaje: evento", "ID"),
        (10, 0): ("ID de control del mensaje", "ST"), (11, 0): ("ID de procesamiento (P producción, T test)", "PT"),
        (12, 0): ("Versión HL7", "ID"),
    },
    "EVN": {(1, 0): ("Tipo de evento", "ID"), (2, 0): ("Fecha/hora del registro del evento", "TS")},
    "PID": {
        (1, 0): ("ID de secuencia", "SI"), (2, 0): ("ID externo del paciente", "CX"),
        (3, 0): ("Identificador del paciente", "CX"), (3, 1): ("Identificador del paciente: ID", "ST"),
        (3, 4): ("Identificador del paciente: autoridad que lo asigna", "HD"),
        (4, 0): ("ID alternativo del paciente", "CX"),
        (5, 0): ("Nombre del paciente", "XPN"), (5, 1): ("Nombre del paciente: apellidos", "ST"),
        (5, 2): ("Nombre del paciente: nombre de pila", "ST"), (5, 3): ("Nombre del paciente: segundo nombre", "ST"),
        (6, 0): ("Apellido de soltera de la madre", "XPN"),
        (7, 0): ("Fecha de nacimiento", "TS"), (8, 0): ("Sexo administrativo (M, F, O, U)", "IS"),
        (11, 0): ("Dirección del paciente", "XAD"), (11, 1): ("Dirección: calle", "ST"),
        (11, 2): ("Dirección: otra designación", "ST"), (11, 3): ("Dirección: ciudad", "ST"),
        (11, 4): ("Dirección: provincia/estado", "ST"), (11, 5): ("Dirección: código postal", "ST"),
        (11, 6): ("Dirección: país", "ID"),
        (13, 0): ("Teléfono particular", "XTN"), (14, 0): ("Teléfono del trabajo", "XTN"),
        (15, 0): ("Idioma principal", "CE"), (16, 0): ("Estado civil", "IS"),
        (18, 0): ("Número de cuenta del paciente", "CX"),
        (19, 0): ("Número de la Seguridad Social (muchos centros españoles envían aquí el DNI)", "ST"),
    },
    "PV1": {
        (1, 0): ("ID de secuencia", "SI"), (2, 0): ("Clase de paciente (I ingresado, O ambulatorio, E urgencias)", "IS"),
        (3, 0): ("Ubicación asignada", "PL"), (3, 1): ("Ubicación: unidad / servicio", "IS"),
        (3, 2): ("Ubicación: habitación", "IS"), (3, 3): ("Ubicación: cama", "IS"),
        (7, 0): ("Médico responsable", "XCN"), (7, 1): ("Médico responsable: ID", "ST"),
        (7, 2): ("Médico responsable: apellidos", "ST"), (7, 3): ("Médico responsable: nombre", "ST"),
        (10, 0): ("Servicio hospitalario", "IS"), (19, 0): ("Número de episodio", "CX"),
        (44, 0): ("Fecha/hora de ingreso", "TS"), (45, 0): ("Fecha/hora de alta", "TS"),
    },
    "AL1": {
        (1, 0): ("ID de secuencia", "SI"),
        (2, 0): ("Tipo de alérgeno (DA medicamento, FA alimento, EA ambiental, MA misc.)", "IS"),
        (3, 0): ("Alérgeno", "CE"), (3, 1): ("Alérgeno: código", "ST"), (3, 2): ("Alérgeno: descripción", "ST"),
        (3, 3): ("Alérgeno: sistema de codificación", "ID"),
        (4, 0): ("Gravedad (SV grave, MO moderada, MI leve)", "IS"), (5, 0): ("Reacción", "ST"),
    },
    "DG1": {
        (1, 0): ("ID de secuencia", "SI"), (2, 0): ("Método de codificación (obsoleto)", "ID"),
        (3, 0): ("Código del diagnóstico", "CE"), (3, 1): ("Diagnóstico: código", "ST"),
        (3, 2): ("Diagnóstico: descripción", "ST"), (3, 3): ("Diagnóstico: sistema (I10 = CIE-10)", "ID"),
        (4, 0): ("Descripción del diagnóstico (texto libre)", "ST"), (5, 0): ("Fecha/hora del diagnóstico", "TS"),
        (6, 0): ("Tipo de diagnóstico (A ingreso, W provisional, F final)", "IS"),
    },
    "OBX": {
        (2, 0): ("Tipo de valor (NM numérico, ST texto, CE codificado...)", "ID"),
        (3, 0): ("Identificador de la observación", "CE"), (3, 1): ("Observación: código (LOINC...)", "ST"),
        (3, 2): ("Observación: descripción", "ST"), (3, 3): ("Observación: sistema de codificación", "ID"),
        (5, 0): ("Valor de la observación", None), (6, 0): ("Unidades", "CE"),
        (7, 0): ("Rango de referencia", "ST"), (8, 0): ("Indicador de anormalidad", "ID"),
        (11, 0): ("Estado del resultado", "ID"), (14, 0): ("Fecha/hora de la observación", "TS"),
    },
    "NK1": {(2, 0): ("Nombre del familiar/contacto", "XPN"), (3, 0): ("Parentesco", "CE")},
}


class HL7Error(ValueError):
    pass


def _unescape(s: str, enc: dict[str, str]) -> str:
    e = enc["esc"]
    if e not in s:
        return s
    mapping = {"F": enc["field"], "S": enc["comp"], "T": enc["sub"], "R": enc["rep"], "E": e,
               ".br": "\n", "H": "", "N": ""}

    def repl(m: re.Match) -> str:
        code = m.group(1)
        if code in mapping:
            return mapping[code]
        if code.startswith("X") and len(code) > 1:
            try:
                return bytes.fromhex(code[1:]).decode("latin-1")
            except ValueError:
                return m.group(0)
        return m.group(0)

    return re.sub(re.escape(e) + r"([^" + re.escape(e) + r"]*)" + re.escape(e), repl, s)


def _segments(text: str) -> list[str]:
    text = text.replace("\x0b", "").replace("\x1c", "")  # MLLP framing
    return [s.strip("﻿ \n") for s in re.split(r"\r\n|\r|\n", text) if s.strip()]


def parse(data: bytes, name: str) -> Dataset:
    text, _ = decode(data)
    ds = Dataset(source=name, format="hl7v2")
    # raw[seg][i] = (message_id, {field_no: [repeat -> [component -> str]]})
    raw: dict[str, list[tuple[str, dict[int, list[list[str]]]]]] = {}
    enc = None
    msg_id, msg_no, versions = "", 0, set()

    for seg in _segments(text):
        sid = seg[:3]
        if sid == "MSH":
            if len(seg) < 8:
                raise HL7Error(f"{name}: segmento MSH demasiado corto")
            enc = {"field": seg[3], "comp": seg[4], "rep": seg[5], "esc": seg[6], "sub": seg[7]}
            msg_no += 1
        elif enc is None:
            raise HL7Error(f"{name}: el mensaje no empieza por MSH")
        parts = seg.split(enc["field"])
        fields: dict[int, list[list[str]]] = {}
        if sid == "MSH":
            numbered = enumerate(parts[2:], start=3)  # MSH-1/MSH-2 are the separators themselves
        else:
            numbered = enumerate(parts[1:], start=1)
        for n, value in numbered:
            if value:
                fields[n] = [
                    [_unescape(c, enc) for c in rep.split(enc["comp"])]
                    for rep in value.split(enc["rep"])
                ]
        if sid == "MSH":
            msg_id = (fields.get(10) or [[f"#{msg_no}"]])[0][0] or f"#{msg_no}"
            versions.add((fields.get(12) or [[""]])[0][0])
        raw.setdefault(sid, []).append((msg_id, fields))

    if not raw:
        raise HL7Error(f"{name}: no hay segmentos HL7")
    ds.notes.append(f"{msg_no} mensaje(s) HL7, versión {', '.join(sorted(v for v in versions if v)) or '?'}.")

    for sid, occurrences in raw.items():
        spec = SPEC.get(sid, {})
        is_z = sid.startswith("Z")
        # A field is addressed by components if any occurrence anywhere has more than one.
        multi = {n for _, f in occurrences for n, reps in f.items() if any(len(r) > 1 for r in reps)}
        records, order = [], {"_message": None}
        for mid, f in occurrences:
            rec: dict = {"_message": mid}
            for n, reps in sorted(f.items()):
                for rep in reps:
                    comps = enumerate(rep, start=1) if n in multi else [(0, rep[0])]
                    for c, v in comps:
                        if not v:
                            continue
                        path = f"{sid}-{n}.{c}" if c else f"{sid}-{n}"
                        order.setdefault(path, (n, c))
                        if path in rec:
                            rec[path] = (rec[path] if isinstance(rec[path], list) else [rec[path]]) + [v]
                        else:
                            rec[path] = v
            records.append(rec)
        ds.tables[sid] = records

        ds.fields.append(Field(entity=sid, path="_message", label="Mensaje",
                               description="ID del mensaje (MSH-10); enlaza este segmento con su mensaje"))
        for path, pos in sorted(((p, o) for p, o in order.items() if o), key=lambda x: x[1]):
            n, c = pos
            desc, dtype = spec.get((n, c)) or spec.get((n, 0)) or ("", None)
            if c and (n, c) not in spec and (n, 0) in spec:
                desc = f"{desc}: componente {c}"
                dtype = None
            if is_z:
                desc = f"Segmento Z propio del centro (no estándar), campo {n}" + (f".{c}" if c else "")
            ds.fields.append(Field(
                entity=sid, path=path, label=path, description=desc,
                custom=is_z, declared_type=dtype,
            ))
    return ds
