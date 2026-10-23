// Utilidades compartidas por las tres pantallas. La lógica (leer archivos, proponer, transformar)
// vive en Python y se pide a la API local (http://127.0.0.1): aquí solo se pinta.

const $ = id => document.getElementById(id);
const pct = p => (p === null || p === undefined) ? "—" : Math.round(p * 100) + " %";
const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
const formatear = v => (v === null || v === undefined || v === "") ? "—"
  : Array.isArray(v) ? v.map(formatear).join(" · ") : typeof v === "object" ? JSON.stringify(v) : String(v);

// ---------- API local ----------
async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo)
  };
  const r = await fetch("/api/" + ruta, opciones);
  const datos = await r.json().catch(() => ({ error: "respuesta no válida" }));
  if (!r.ok) throw new Error(datos.error || `error ${r.status}`);
  return datos;
}

function base64ABytes(b64) {
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function archivoABase64(file) {
  return new Promise((ok, mal) => {
    const lector = new FileReader();
    lector.onload = () => ok(String(lector.result).split(",")[1] || "");
    lector.onerror = () => mal(new Error("no se pudo leer el archivo"));
    lector.readAsDataURL(file);
  });
}

let temporizadorToast;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.classList.add("visible");
  clearTimeout(temporizadorToast);
  temporizadorToast = setTimeout(() => t.classList.remove("visible"), 3600);
}

function descargar(nombre, contenido, tipo) {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = document.createElement("a");
  a.href = url; a.download = nombre; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- Nombres comprensibles para cualquier persona ----------
// Los campos del destino traen su concepto (expected/); se traduce a lenguaje llano.
const CONCEPTOS_HUMANOS = {
  id_paciente:      { nombre: "Nº de historia clínica", ayuda: "El número con el que el hospital identifica al paciente" },
  dni:              { nombre: "DNI", ayuda: "Documento nacional de identidad" },
  nombre:           { nombre: "Nombre", ayuda: "Nombre de pila del paciente" },
  apellidos:        { nombre: "Apellidos", ayuda: "Apellidos del paciente" },
  fecha_nacimiento: { nombre: "Fecha de nacimiento", ayuda: "Día en que nació el paciente" },
  sexo:             { nombre: "Sexo", ayuda: "Cada sistema lo escribe a su manera: H/M, M/F, male/female" },
  telefono:         { nombre: "Teléfono", ayuda: "Teléfono de contacto" },
  calle:            { nombre: "Calle", ayuda: "Calle y número del domicilio" },
  ciudad:           { nombre: "Ciudad", ayuda: "Ciudad o localidad donde vive" },
  codigo_postal:    { nombre: "Código postal", ayuda: "Código postal del domicilio" },
  grupo_sanguineo:  { nombre: "Tipo de sangre", ayuda: "Grupo sanguíneo, por ejemplo A+ o O-" },
  peso:             { nombre: "Peso", ayuda: "Peso del paciente en kilos" },
  altura:           { nombre: "Altura", ayuda: "Altura (talla) del paciente en centímetros" },
  alergia:          { nombre: "Alergias", ayuda: "Sustancias que le provocan reacción, por ejemplo la penicilina" },
  medico:           { nombre: "Médico responsable", ayuda: "Médico que atiende al paciente" }
};

// Campo del destino → { nombre, ayuda, tecnico }
function humanoDestino(t) {
  const h = CONCEPTOS_HUMANOS[t.concept];
  const hoja = String(t.leaf || t.path.split(".").pop()).replace(/^@/, "").replace(/_/g, " ");
  return { nombre: h ? h.nombre : hoja.charAt(0).toUpperCase() + hoja.slice(1), ayuda: (h && h.ayuda) || t.description || "", tecnico: t.path };
}

// Columna del hospital → { nombre, tecnico }: la descripción del estándar si la hay, si no la etiqueta
function humanoOrigen(col) {
  if (!col) return { nombre: "—", tecnico: "" };
  const desc = (col.description || "").split(" — ")[0];
  const nombre = desc && desc.length < 70 ? desc : col.label;
  return { nombre: nombre.charAt(0).toUpperCase() + nombre.slice(1), tecnico: col.column };
}

// ---------- Entidades: agrupación y cabecera visual ----------
function agruparPorGrupo(targets) {
  const grupos = new Map();
  targets.forEach(t => {
    const g = t.path.includes(".") ? t.path.split(".")[0] : "datos";
    if (!grupos.has(g)) grupos.set(g, []);
    grupos.get(g).push(t);
  });
  return [...grupos.entries()];
}

// ---------- Ejemplos sintéticos del reto ----------
const HOSPITALES_DEMO = [
  { id: "hospitalA", archivo: "huca_oviedo_hl7v23.hl7", nombre: "Hospital Universitario Central de Asturias", corto: "HUCA", ciudad: "Oviedo", formato: "HL7" },
  { id: "hospitalB", archivo: "hospital_leon_fhir.json", nombre: "Hospital Universitario de León", corto: "H. de León", ciudad: "León", formato: "FHIR" },
  { id: "hospitalC", archivo: "hospital_alvarez_buylla.csv", nombre: "Hospital Álvarez-Buylla", corto: "H. Álvarez-Buylla", ciudad: "Mieres", formato: "EXCEL" }
];
const FORMATOS = { csv: "CSV", excel: "Excel", fhir: "FHIR", json: "JSON", hl7v2: "HL7 v2", xml: "XML" };

// Ejemplos sintéticos (examples/): nombre legible, grupo y formato por la extensión
const EJEMPLOS = {
  "huca_oviedo_hl7v23.hl7": ["Hospitales del reto", "HUCA (Oviedo)"],
  "hospital_leon_fhir.json": ["Hospitales del reto", "H. de León", "FHIR"],
  "hospital_alvarez_buylla.csv": ["Hospitales del reto", "H. Álvarez-Buylla (Mieres)"],
  "hospital_a_diagnosticos.hl7": ["Otros ejemplos", "Diagnósticos"],
  "hospital_b_condiciones.json": ["Otros ejemplos", "Condiciones", "FHIR"],
  "hospital_c_messy.xlsx": ["Otros ejemplos", "Hoja desordenada"],
  "hard/h1_ingles_comas.csv": ["Datos difíciles", "En inglés y con comas"],
  "hard/h2_cifrado.csv": ["Datos difíciles", "Cabeceras en clave"],
  "hard/h3_hl7_v25.hl7": ["Datos difíciles", "HL7 versión 2.5"],
  "hard/h4_fhir_completo.json": ["Datos difíciles", "FHIR completo", "FHIR"],
  "hard/h5_excel_dificil.xlsx": ["Datos difíciles", "Excel complicado"]
};
const FORMATO_EXTENSION = { hl7: "HL7 v2", json: "JSON", csv: "CSV", tsv: "CSV", txt: "texto", xlsx: "Excel", xml: "XML", ndjson: "JSON" };

function describirEjemplo(archivo) {
  const [grupo, nombre, formato] = EJEMPLOS[archivo] || [archivo.startsWith("hard/") ? "Datos difíciles" : "Otros ejemplos",
    archivo.replace(/^hard\//, "").replace(/\.[^.]+$/, "").replace(/_/g, " ")];
  return { grupo, nombre, formato: formato || FORMATO_EXTENSION[archivo.split(".").pop().toLowerCase()] || "" };
}

// ---------- Iconos (SVG en línea, heredan el color) ----------
const svg = (d, t = 22) => `<svg viewBox="0 0 24 24" width="${t}" height="${t}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICONO = {
  hospital: t => svg('<path d="M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 10h4a1 1 0 0 1 1 1v10M2 21h20M9.5 7v4M7.5 9h4M8 15h3M8 18h3"/>', t),
  persona: t => svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>', t),
  casa: t => svg('<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>', t),
  salud: t => svg('<path d="M12 21s-8-5.2-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.8-8 11-8 11z"/><path d="M9 11h6M12 8v6"/>', t),
  lista: t => svg('<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>', t),
  ojo: t => svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>', t),
  check: t => svg('<path d="M5 12l5 5L20 7"/>', t)
};

function iconoGrupo(nombre, t = 20) {
  const n = String(nombre).toLowerCase();
  if (/direc|domic|address/.test(n)) return ICONO.casa(t);
  if (/clin|salud|medic|alerg/.test(n)) return ICONO.salud(t);
  if (/pacien|patient|persona/.test(n)) return ICONO.persona(t);
  return ICONO.lista(t);
}
function nombreGrupo(nombre) {
  const s = String(nombre).replace(/[_-]+/g, " ").trim().replace(/clinicos/i, "clínicos").replace(/direccion/i, "dirección");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------- Anillo de porcentaje ----------
// valor: 0..1 o null (sin datos). Devuelve el SVG como texto.
function anillo(valor, tam = 56) {
  const r = 22, l = 2 * Math.PI * r;
  const v = valor === null || valor === undefined ? 0 : Math.max(0, Math.min(1, valor));
  const color = valor === null || valor === undefined ? "var(--borde)" : v >= 0.85 ? "var(--verde)" : v >= 0.6 ? "var(--ambar)" : "var(--rojo)";
  const texto = valor === null || valor === undefined ? "—" : Math.round(v * 100);
  return `<svg class="anillo" viewBox="0 0 56 56" width="${tam}" height="${tam}" aria-hidden="true">
    <circle cx="28" cy="28" r="${r}" fill="none" stroke="var(--azul-claro)" stroke-width="6"/>
    <circle cx="28" cy="28" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="${(l * v).toFixed(1)} ${l.toFixed(1)}" transform="rotate(-90 28 28)"/>
    <text x="28" y="29" text-anchor="middle" dominant-baseline="middle">${texto}${texto === "—" ? "" : '<tspan dx="1" font-size="9">%</tspan>'}</text>
  </svg>`;
}
