// Traducir datos: origen (cualquier formato) → destino (un ejemplo, en cualquier formato) →
// propuesta (reglas o IA local) → revisión humana → receta aprobada → archivo en el formato del destino.
// Toda la lógica está en Python (API local). Aquí se guardan solo las decisiones de quien revisa.

const estado = {
  destino: null,      // GET /api/expected?destination=…
  llevar: new Set(),  // columnas sin usar que viajan como campo extra (las demás se descartan, anotado)
  subida: null,       // POST /api/upload: upload_id, columns, ai_view, samples, notes
  propuesta: null,    // POST /api/propose: draft, ranking, previews, reusable
  decisiones: {},     // target → { status, from, transforms, issues, confidence, why, preview }
  revisado: new Set(),// targets que una persona ha revisado
  sinDato: new Set(), // targets que se aceptan vacíos
  recien: null,
  ultimo: null,       // resultado de aprobar / reutilizar
  directo: null       // destino a medida: { formato, campos: [{ name, type, required, multiple, from, incluir }] }
};

const ALTA = 0.85;
const nivel = p => p === null || p === undefined ? "bajo" : p >= 0.85 ? "alto" : p >= 0.7 ? "medio" : "bajo";
const objetivo = path => estado.destino.targets.find(t => t.path === path);
const columna = c => estado.subida.columns.find(x => x.column === c);
const nombreColumnas = cols => cols.map(c => humanoOrigen(columna(c)).nombre).join(" + ");

// ---------- Carga ----------
function configurarSelector() {
  const label = $("sel-origen"), input = $("file-origen");
  input.addEventListener("change", () => input.files[0] && subirArchivo(input.files[0]));
  label.addEventListener("dragover", e => { e.preventDefault(); label.classList.add("arrastrando"); });
  label.addEventListener("dragleave", () => label.classList.remove("arrastrando"));
  label.addEventListener("drop", e => {
    e.preventDefault(); label.classList.remove("arrastrando");
    if (e.dataTransfer.files[0]) subirArchivo(e.dataTransfer.files[0]);
  });
}

async function subirArchivo(file) {
  $("sel-ejemplo").value = "";
  try {
    pensando("Leyendo el archivo en este equipo…");
    await cargarSubida(await api("upload", { name: file.name, content_b64: await archivoABase64(file) }));
  } catch (e) { pensando(null); toast("No se pudo leer el archivo: " + e.message); }
}

async function cargarEjemplo(nombre) {
  try {
    pensando("Leyendo el ejemplo…");
    await cargarSubida(await api("upload", { example: nombre }));
  } catch (e) { pensando(null); toast(e.message); }
}

// Ejemplos sintéticos: un solo desplegable, agrupado (los del reto primero)
function pintarEjemplos(ejemplos) {
  const sel = $("sel-ejemplo");
  const grupos = new Map(["Hospitales del reto", "Otros ejemplos", "Datos difíciles"].map(g => [g, []]));
  ejemplos.forEach(e => {
    const info = describirEjemplo(e.name);
    if (!grupos.has(info.grupo)) grupos.set(info.grupo, []);
    grupos.get(info.grupo).push({ ...info, archivo: e.name });
  });
  sel.innerHTML = `<option value="">…o prueba con un ejemplo sintético</option>` + [...grupos.entries()].filter(([, l]) => l.length).map(([g, lista]) =>
    `<optgroup label="${esc(g)}">${lista.map(x => `<option value="${esc(x.archivo)}">${esc(x.nombre)} · ${esc(x.formato)}</option>`).join("")}</optgroup>`).join("");
  sel.onchange = () => {
    if (!sel.value) return;
    cargarEjemplo(sel.value);
  };
}

async function cargarSubida(subida) {
  estado.subida = subida;
  $("nombre-origen").textContent = `${subida.name} · ${FORMATOS[subida.format] || subida.format} · ${subida.rows} registros · ${subida.columns.length} columnas`;
  $("resultado").classList.add("oculto");
  pintarNotas();
  pintarIA();
  if (estado.directo && $("todos-campos").checked) await camposDelOrigen();   // la lista sale del archivo nuevo
  else await proponer();
}

async function proponer() {
  if (!estado.subida) return;
  const modelo = $("proponente").value;
  pensando(modelo === "rules" ? "Proponiendo con reglas…" : `La IA local (${modelo}) está proponiendo. Solo ve la columna central de «Lo que ve la IA»…`);
  try {
    const p = await api("propose", { upload_id: estado.subida.upload_id, model: modelo, destination: estado.destino.key });
    estado.propuesta = p;
    estado.decisiones = {};
    for (const [t, f] of Object.entries(p.draft.fields)) {
      estado.decisiones[t] = { ...f, preview: p.previews[t] };
    }
    estado.revisado = new Set();
    // Lo que la persona ató a una columna al hacer la lista ya está decidido; lo dudoso sigue por revisar
    for (const [t, f] of Object.entries(p.draft.fields)) {
      if (f.proposed_by === "direct" && f.status === "mapped") estado.revisado.add(t);
    }
    estado.sinDato = new Set();
    estado.llevar = new Set();
    pintarAvisoReceta();
    const info = p.draft.proposer || {};
    $("estado-ia").textContent = info.fallback_reason ? `Sin modelo local: propuesto por reglas (${info.fallback_reason})`
      : info.seconds !== undefined ? `Propuesto por ${info.model} en ${info.seconds} s` : "";
  } catch (e) {
    toast(e.message);
  } finally {
    pensando(null);
  }
  render();
}

function pensando(texto) {
  $("pensando").classList.toggle("oculto", !texto);
  if (texto) $("pensando-texto").textContent = texto;
  $("btn-confirmar").disabled = !!texto || $("btn-confirmar").disabled;
}

function pintarNotas() {
  const n = estado.subida.notes || [];
  $("notas").classList.toggle("oculto", !n.length);
  $("notas").innerHTML = `<strong>Al leer el archivo:</strong><ul>${n.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
}

// ---------- Receta ya conocida ----------
function pintarAvisoReceta() {
  const r = estado.propuesta && estado.propuesta.reusable;
  $("aviso-receta").classList.toggle("oculto", !r);
  if (r) $("aviso-texto").innerHTML = `Ya conozco este formato: la receta <b>${esc(r.name)}</b> la aprobó ${esc(r.approved_by)} (${new Date(r.at).toLocaleString("es-ES")}). Se puede aplicar sin volver a proponer.`;
}

async function reutilizar() {
  const r = estado.propuesta.reusable;
  try {
    mostrarResultado(await api("run", { upload_id: estado.subida.upload_id, recipe: r.name, destination: estado.destino.key }), "reutilizada");
    toast(`Receta ${r.name} aplicada sin volver a proponer`);
  } catch (e) { toast(e.message); }
}

// ---------- Lo que ve la IA vs tus datos ----------
function vistaIA(c) {
  if (c.values) return `categorías: ${c.values.join(", ")}`;
  if (c.numbers) return `números: mín ${c.numbers.min} · mediana ${c.numbers.median} · máx ${c.numbers.max}`;
  if (c.concepts) return `terminología: ${c.concepts.recognised} de ${c.concepts.of} reconocidos (${c.concepts.systems.join(", ")})`;
  if (c.masked_samples) return c.masked_samples.join(" · ");
  return "—";
}

function pintarIA() {
  $("icono-ojo").innerHTML = ICONO.ojo(16);
  const filas = estado.subida.ai_view.columns.map(c => {
    const real = estado.subida.samples[c.column] || [];
    return `<tr><td><b>${esc(c.column)}</b><small>${esc(c.description || "")}</small></td>
      <td class="ia">${esc(vistaIA(c))}</td>
      <td class="real">${esc(real.map(formatear).join(" · ") || "—")}</td></tr>`;
  }).join("");
  $("tabla-ia").innerHTML = `<table class="tabla"><thead><tr><th>Columna</th><th>Lo que ve la IA</th><th>Tus datos (solo aquí)</th></tr></thead><tbody>${filas}</tbody></table>`;
}

// ---------- Cambios de quien revisa ----------
async function elegirColumnas(target, cols) {
  // Una columna alimenta un solo campo: si la tenía otro campo, ese se queda sin dato
  for (const [t, d] of Object.entries(estado.decisiones)) {
    if (t !== target && d.from.some(c => cols.includes(c))) {
      Object.assign(d, { status: "no_data", from: [], transforms: [], issues: [], preview: null, confidence: null });
      estado.revisado.delete(t);
      toast(`«${humanoDestino(objetivo(t)).nombre}» se queda sin dato: su columna pasa a «${humanoDestino(objetivo(target)).nombre}»`);
    }
  }
  try {
    const r = await api("field", { upload_id: estado.subida.upload_id, target, from: cols, destination: estado.destino.key });
    const opcion = (estado.propuesta.ranking[target] || []).find(o => o.from.join("|") === cols.join("|"));
    Object.assign(estado.decisiones[target], {
      status: r.status, from: r.from, transforms: r.transforms, issues: r.issues, preview: r.preview,
      confidence: opcion ? opcion.confidence : null, why: opcion ? opcion.why : ["elegido a mano"]
    });
  } catch (e) { toast(e.message); }
  estado.revisado.delete(target);
  estado.sinDato.delete(target);
  estado.recien = target;
  render();
}

function quitar(target) {
  Object.assign(estado.decisiones[target], { status: "no_data", from: [], transforms: [], issues: [], preview: null, confidence: null });
  estado.revisado.delete(target);
  estado.recien = target;
  render();
}

function darPorBueno(targets) {
  plegar(targets, () => targets.forEach(t => {
    const d = estado.decisiones[t];
    if (d.status === "pending") d.status = "mapped";   // la persona decide: queda registrado como cambio
    estado.revisado.add(t);
  }));
}

function aceptarVacios(targets) {
  targets.forEach(t => {
    if (objetivo(t).required) return;
    Object.assign(estado.decisiones[t], { status: "no_data", from: [], transforms: [] });
    estado.sinDato.add(t);
    estado.revisado.add(t);
  });
  render();
}

function plegar(targets, cambio) {
  const filas = targets.map(t => document.querySelector(`.conexion[data-target="${CSS.escape(t)}"]`)).filter(Boolean);
  filas.forEach(f => { f.style.maxHeight = f.offsetHeight + "px"; f.getBoundingClientRect(); f.classList.add("plegando"); });
  setTimeout(() => { cambio(); estado.recien = targets.length === 1 ? targets[0] : null; render(); }, filas.length ? 320 : 0);
}

// ---------- Render ----------
function render() {
  const listo = !!(estado.subida && estado.propuesta);
  $("tablero").classList.toggle("oculto", !listo);
  $("vacio-mapeo").classList.toggle("oculto", listo);
  $("marcador").classList.toggle("oculto", !listo);
  if (!listo) { $("btn-confirmar").disabled = true; return; }

  const targets = estado.destino.targets.map(t => t.path);
  const conDato = targets.filter(t => estado.decisiones[t].from.length);
  const pendientes = conDato.filter(t => !estado.revisado.has(t));
  const revisados = conDato.filter(t => estado.revisado.has(t));
  const faltan = targets.filter(t => !estado.decisiones[t].from.length && !estado.sinDato.has(t));
  const usados = new Set(conDato.flatMap(t => estado.decisiones[t].from));
  const sobrantes = estado.subida.columns.filter(c => !usados.has(c.column));

  $("c-conexiones").textContent = conDato.length;
  $("c-revisadas").textContent = revisados.length + estado.sinDato.size;
  $("c-pendientes").textContent = pendientes.length;
  $("c-restantes").textContent = faltan.length;
  const confianzas = conDato.map(t => estado.decisiones[t].confidence).filter(c => c !== null && c !== undefined);
  const media = confianzas.length ? confianzas.reduce((a, b) => a + b, 0) / confianzas.length : null;
  $("c-anillo-compat").innerHTML = anillo(media, 46);
  $("c-compat").textContent = pct(media);
  const cob = conDato.length / targets.length;
  $("c-anillo-cob").innerHTML = anillo(cob, 46);
  $("c-cob").textContent = pct(cob);
  $("c-barra").style.width = Math.round(100 * (revisados.length + estado.sinDato.size) / targets.length) + "%";

  const bloqueo = [];
  if (pendientes.length) bloqueo.push(`revisa ${pendientes.length} campo(s)`);
  if (faltan.length) bloqueo.push(`elige dato o «Continuar sin dato» en ${faltan.length} campo(s)`);
  if (!$("revisor").value.trim()) bloqueo.push("escribe quién revisa");
  $("btn-confirmar").disabled = bloqueo.length > 0;
  $("btn-confirmar").title = bloqueo.length ? "Para aprobar: " + bloqueo.join(", ") : "";
  $("estado").textContent = bloqueo.length ? "Para aprobar: " + bloqueo.join(", ") + "."
    : "Todo revisado. Al aprobar se guarda la receta con tu nombre y se convierten los datos.";

  renderRevisados(revisados);
  renderPendientes(pendientes);
  renderFaltan(faltan);
  renderSobrantes(sobrantes);
  estado.recien = null;
}

function bloqueDestino(t) {
  const h = humanoDestino(t);
  const el = document.createElement("div");
  el.className = "campo-vis destino";
  el.innerHTML = `<div class="campo-info"><div class="campo-nombre"><span></span>${t.required ? '<span class="marca-oblig">obligatorio</span>' : ""}</div><div class="campo-tecnico"></div></div>`;
  el.querySelector(".campo-nombre span").textContent = h.nombre;
  el.querySelector(".campo-tecnico").textContent = h.tecnico;
  if (h.ayuda) el.title = h.ayuda;
  return el;
}

function bloqueOrigen(cols) {
  const el = document.createElement("div");
  el.className = "campo-vis origen";
  el.innerHTML = `<div class="campo-info"><div class="campo-nombre"><span></span></div><div class="campo-tecnico"></div></div>`;
  el.querySelector(".campo-nombre span").textContent = nombreColumnas(cols);
  el.querySelector(".campo-tecnico").textContent = cols.join(" + ");
  const c = columna(cols[0]);
  if (c && c.custom) el.querySelector(".campo-nombre").insertAdjacentHTML("beforeend", '<span class="marca-custom">personalizado</span>');
  if (c && c.sensitive) el.querySelector(".campo-nombre").insertAdjacentHTML("beforeend", '<span class="marca-sensible">dato personal</span>');
  return el;
}

// Opciones para elegir columna: primero las candidatas mejor puntuadas, luego todas
function selectorColumnas(target, actual, texto) {
  const sel = document.createElement("select");
  sel.className = actual ? "cambiar" : "elegir-origen";
  sel.innerHTML = `<option value="">${esc(texto)}</option>`;
  const usadas = new Set(Object.entries(estado.decisiones).filter(([t]) => t !== target).flatMap(([, d]) => d.from));
  const vistas = new Set();
  const grupo1 = document.createElement("optgroup"); grupo1.label = "Sugeridas";
  (estado.propuesta.ranking[target] || []).filter(o => o.confidence > 0.3).forEach(o => {
    const clave = o.from.join("|"); vistas.add(clave);
    grupo1.insertAdjacentHTML("beforeend", `<option value="${esc(clave)}">${esc(nombreColumnas(o.from))} (${esc(o.from.join(" + "))}) · ${pct(o.confidence)}${o.from.some(c => usadas.has(c)) ? " · en uso" : ""}</option>`);
  });
  const grupo2 = document.createElement("optgroup"); grupo2.label = "Todas las columnas";
  estado.subida.columns.filter(c => !vistas.has(c.column)).forEach(c => {
    grupo2.insertAdjacentHTML("beforeend", `<option value="${esc(c.column)}">${esc(humanoOrigen(c).nombre)} (${esc(c.column)})${usadas.has(c.column) ? " · en uso" : ""}</option>`);
  });
  if (grupo1.children.length) sel.appendChild(grupo1);
  sel.appendChild(grupo2);
  sel.value = actual ? actual.join("|") : "";
  sel.onchange = () => sel.value && elegirColumnas(target, sel.value.split("|"));
  return sel;
}

function renderPendientes(lista) {
  $("n-pendientes").textContent = lista.length;
  const altas = lista.filter(t => estado.decisiones[t].status === "mapped" && (estado.decisiones[t].confidence || 0) >= ALTA
    && !(estado.decisiones[t].issues || []).length && !(estado.decisiones[t].preview || {}).problem);
  const btn = $("btn-aprobar-altas");
  btn.classList.toggle("oculto", !altas.length);
  btn.textContent = `✓ Dar por buenas las de confianza alta sin avisos (${altas.length})`;
  btn.onclick = () => darPorBueno(altas);

  const cont = $("lista-pendientes");
  cont.innerHTML = lista.length ? "" : `<div class="todo-ok">✓ No queda nada por revisar.</div>`;
  document.querySelector(".leyenda-conexion").classList.toggle("oculto", !lista.length);
  // Primero lo que necesita ojos humanos: pendientes y confianza baja
  const orden = t => (estado.decisiones[t].status === "pending" ? -1 : 0) + (estado.decisiones[t].confidence || 0);
  [...lista].sort((a, b) => orden(a) - orden(b)).forEach(t => {
    const d = estado.decisiones[t];
    const fila = document.createElement("div");
    fila.className = `conexion ${nivel(d.confidence)}` + (d.status === "pending" ? " pendiente-humano" : "") + (estado.recien === t ? " recien" : "");
    fila.dataset.target = t;

    const p = d.preview || {};
    const conector = document.createElement("div");
    conector.className = "conector";
    conector.innerHTML = `
      <span class="porcentaje ${nivel(d.confidence)}"></span>
      <div class="linea-con"><i></i></div>
      <div class="valores"><code class="antes"></code><span class="mini-flecha">→</span><code class="despues"></code></div>
      <div class="motivo"></div><ul class="avisos"></ul>`;
    conector.querySelector(".porcentaje").textContent = pct(d.confidence);
    conector.querySelector(".antes").textContent = formatear(p.before);
    conector.querySelector(".despues").textContent = p.problem ? "✕ " + p.problem : formatear(p.after);
    conector.querySelector(".despues").classList.toggle("cambia", !p.problem && formatear(p.before) !== formatear(p.after));
    conector.querySelector(".despues").classList.toggle("error", !!p.problem);
    conector.querySelector(".motivo").textContent = (d.why || []).join(" · ") + (d.proposed_by && d.proposed_by !== "rules" ? ` · propuesto por ${d.proposed_by}` : "");
    conector.querySelector(".avisos").innerHTML = (d.issues || []).map(i => `<li>${esc(i)}</li>`).join("");

    const destino = bloqueDestino(objetivo(t));
    destino.querySelector(".campo-info").appendChild(selectorColumnas(t, d.from, "Cambiar columna…"));

    const acciones = document.createElement("div");
    acciones.className = "acciones-con";
    acciones.innerHTML = `<button class="btn-ok" title="${d.status === "pending" ? "Lo decido yo: quedará registrado" : "Es correcto"}">✓<span>${d.status === "pending" ? "Lo apruebo" : "Correcto"}</span></button><button class="btn-quitar" title="No usar esta columna">✕</button>`;
    acciones.querySelector(".btn-ok").onclick = () => darPorBueno([t]);
    acciones.querySelector(".btn-quitar").onclick = () => quitar(t);

    fila.append(bloqueOrigen(d.from), conector, destino, acciones);
    cont.appendChild(fila);
  });
}

function renderRevisados(lista) {
  const vacios = [...estado.sinDato];
  $("n-revisadas").textContent = lista.length + vacios.length;
  $("sec-revisadas").classList.toggle("oculto", !lista.length && !vacios.length);
  const cont = $("lista-revisadas");
  cont.innerHTML = "";
  vacios.forEach(t => {
    const b = document.createElement("button");
    b.className = "ficha vacia";
    b.innerHTML = `<span class="ficha-check">–</span><span></span><small class="ficha-cod">sin dato</small>`;
    b.children[1].textContent = humanoDestino(objetivo(t)).nombre;
    b.title = "Se enviará vacío. Pulsa para buscarle un dato";
    b.onclick = () => { estado.sinDato.delete(t); estado.revisado.delete(t); render(); };
    cont.appendChild(b);
  });
  lista.forEach(t => {
    const d = estado.decisiones[t];
    const b = document.createElement("button");
    b.className = "ficha";
    b.innerHTML = `<span class="ficha-check">✓</span><span></span><span class="ficha-flecha">←</span><span></span><small class="ficha-cod"></small>`;
    b.children[1].textContent = humanoDestino(objetivo(t)).nombre;
    b.children[3].textContent = nombreColumnas(d.from);
    b.querySelector(".ficha-cod").textContent = d.from.join(" + ");
    b.title = "Pulsa para volver a revisarlo";
    b.onclick = () => { estado.revisado.delete(t); estado.recien = t; render(); };
    cont.appendChild(b);
  });
}

function renderFaltan(lista) {
  $("n-faltan").textContent = lista.length;
  const opcionales = lista.filter(t => !objetivo(t).required);
  $("btn-todos-sin-dato").textContent = `Continuar sin los opcionales (${opcionales.length})`;
  $("btn-todos-sin-dato").classList.toggle("oculto", !opcionales.length);
  $("btn-todos-sin-dato").onclick = () => aceptarVacios(opcionales);
  $("sec-faltan").classList.toggle("oculto", !lista.length);
  const cont = $("lista-faltan");
  cont.innerHTML = "";
  lista.forEach(t => {
    const obj = objetivo(t), d = estado.decisiones[t];
    const tarjeta = document.createElement("div");
    tarjeta.className = "falta-campo" + (obj.required ? " oblig" : "") + (estado.recien === t ? " recien" : "");
    tarjeta.appendChild(bloqueDestino(obj));
    const ej = document.createElement("div");
    ej.className = "falta-ejemplo";
    ej.textContent = `Ejemplo esperado: ${formatear(obj.example)}`;
    tarjeta.appendChild(ej);
    if ((d.issues || []).length) tarjeta.insertAdjacentHTML("beforeend", `<ul class="avisos">${d.issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul>`);
    tarjeta.appendChild(selectorColumnas(t, null, "Elegir dato del hospital…"));
    const saltar = document.createElement("button");
    saltar.className = "btn-sin-dato";
    saltar.textContent = obj.required ? "Obligatorio: hace falta un dato" : "Continuar sin dato";
    saltar.disabled = obj.required;
    saltar.onclick = () => aceptarVacios([t]);
    tarjeta.appendChild(saltar);
    cont.appendChild(tarjeta);
  });
}

function renderSobrantes(lista) {
  $("n-sobrantes").textContent = lista.length;
  const nombres = new Set(lista.map(c => c.column));
  [...estado.llevar].forEach(c => nombres.has(c) || estado.llevar.delete(c));   // ya usada en un campo
  $("resumen-extras").textContent = lista.length ? `· ${estado.llevar.size} se llevan como extra, ${lista.length - estado.llevar.size} se descartan` : "";
  const cont = $("lista-sobrantes");
  cont.innerHTML = "";
  lista.forEach(c => {
    const fila = document.createElement("div");
    fila.className = "ficha-sobrante";
    fila.appendChild(bloqueOrigen([c.column]));
    const llevar = document.createElement("label");
    llevar.className = "llevar-extra";
    llevar.title = "Viaja como campo extra del destino; si no, se descarta y queda anotado";
    llevar.innerHTML = `<input type="checkbox"${estado.llevar.has(c.column) ? " checked" : ""}> Llevar`;
    llevar.querySelector("input").onchange = e => {
      e.target.checked ? estado.llevar.add(c.column) : estado.llevar.delete(c.column);
      render();
    };
    fila.appendChild(llevar);
    const val = document.createElement("code");
    val.textContent = formatear((estado.subida.samples[c.column] || [])[0]);
    const sel = document.createElement("select");
    sel.className = "elegir-origen";
    sel.innerHTML = `<option value="">Conectar a…</option>` + estado.destino.targets.map(t =>
      `<option value="${esc(t.path)}">${esc(humanoDestino(t).nombre)}${estado.decisiones[t.path].from.length ? " · ya tiene dato" : ""}</option>`).join("");
    sel.onchange = () => sel.value && elegirColumnas(sel.value, [c.column]);
    fila.append(val, sel);
    cont.appendChild(fila);
  });
}

// ---------- Aprobar y convertir ----------
async function confirmar() {
  const draft = { fields: {} };
  for (const [t, d] of Object.entries(estado.decisiones)) {
    draft.fields[t] = { status: d.from.length ? d.status : "no_data", from: d.from, transforms: d.transforms || [] };
  }
  try {
    $("btn-confirmar").disabled = true;
    mostrarResultado(await api("approve", { upload_id: estado.subida.upload_id, draft, by: $("revisor").value.trim(),
      carry: [...estado.llevar], destination: estado.destino.key }), "aprobada");
    toast("Receta aprobada y guardada. La próxima vez se reutiliza sin proponer.");
  } catch (e) {
    toast("No se puede aprobar: " + e.message);
    render();
  }
}

function mostrarResultado(r, como) {
  estado.ultimo = r;
  const rep = r.report, rec = r.recipe;
  $("resultado-sub").textContent = `Receta ${rec.recipe} · ${como} por ${rec.approval.by} · ${new Date(rec.approval.at).toLocaleString("es-ES")} · huella ${rec.approval.sha256.slice(0, 12)}…`;
  const cambiados = Object.values(rec.fields).filter(f => f.changed_by).length;
  $("resumen").innerHTML = `
    <span><b>${rep.accepted}</b> de ${rep.rows} registros convertidos</span>
    <span><b>${rep.rejected}</b> apartados</span>
    <span><b>${Object.values(rec.fields).filter(f => f.status === "mapped").length}</b> campos con dato</span>
    <span><b>${cambiados}</b> cambiados por quien revisa</span>
    ${rep.items !== undefined ? `<span><b>${rep.items}</b> elementos agrupados</span>` : ""}
    ${rep.custom_fields ? `<span><b>${rep.custom_fields.carried.length}</b> extra · <b>${rep.custom_fields.dropped.length}</b> descartados</span>` : ""}`;
  const vacios = Object.entries(rep.empty_fields || {});
  $("pendientes").innerHTML =
    (rep.errors.length ? `<div class="alerta error"><strong>Registros apartados (no cumplen tu formato, no se corrigen solos):</strong><ul>${rep.errors.slice(0, 12).map(e => `<li>fila ${e.row}: ${esc(e.field)} — ${esc(e.reason)}</li>`).join("")}</ul></div>` : "") +
    (vacios.length ? `<div class="alerta aviso-amarillo"><strong>Campos vacíos:</strong> ${vacios.map(([k, n]) => `${esc(k)} (${n})`).join(", ")}</div>` : "");
  $("pre-receta").textContent = JSON.stringify(rec, null, 2);
  const o = r.output;
  const texto = o.format === "excel" ? JSON.stringify(r.records, null, 2)
    : new TextDecoder().decode(base64ABytes(o.content_b64));
  $("pre-salida").textContent = texto.length > 6000 ? texto.slice(0, 6000) + "\n…" : texto;
  $("dl-salida").textContent = `Descargar ${o.filename} (${o.label})`;
  $("problemas-salida").classList.toggle("oculto", !o.problems.length);
  $("problemas-salida").innerHTML = o.problems.length ? `<strong>La salida no supera la comprobación de ${esc(o.label)}:</strong><ul>${o.problems.slice(0, 12).map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  $("resultado").classList.remove("oculto");
  $("resultado").scrollIntoView({ behavior: "smooth" });
}

// ---------- Destino ----------
async function pintarDestinos(elegido) {
  const lista = await api("destinations");
  const sel = $("sel-destino");
  const origen = { carpeta: "", ejemplo: " · ejemplo", subido: " · subido", medida: " · a medida", guardado: " · guardado" };
  sel.innerHTML = lista.map(d => `<option value="${esc(d.key)}">${esc(d.name)} · ${esc(d.label)} · ${d.fields} campos${origen[d.origin] || ""}</option>`).join("");
  const clave = elegido && lista.some(d => d.key === elegido) ? elegido : (lista[0] || {}).key;
  if (clave) await elegirDestino(clave, false);
}

async function elegirDestino(clave, reproponer = true) {
  try {
    estado.destino = await api("expected?destination=" + encodeURIComponent(clave));
    $("sel-destino").value = clave;
    const d = estado.destino;
    $("nombre-destino").textContent = `${d.name} · ${d.label} · ${d.targets.length} campos`;
    $("contexto-destino").textContent = [d.pack ? `vocabulario: ${d.pack}` : "sin vocabulario de dominio",
      d.group_by ? `agrupa por ${d.group_by}` : "", d.constants ? `${d.constants} valores fijos del ejemplo` : ""].filter(Boolean).join(" · ");
    $("ver-destino").href = "modelos.html?destino=" + encodeURIComponent(clave);
    if (reproponer && estado.subida) await proponer();
    else render();
  } catch (e) { toast("No se puede usar ese destino: " + e.message); }
}

async function subirDestino(files) {
  // Un ejemplo de la salida y, si se elige a la vez, su <nombre>.rules.json
  const lista = [...files];
  const reglas = lista.find(f => f.name.toLowerCase().endsWith(".rules.json"));
  const file = lista.find(f => f !== reglas);
  if (!file) { toast("Elige el ejemplo de la salida (y, si quieres, su .rules.json)"); return; }
  try {
    pensando("Leyendo el ejemplo del destino…");
    const cuerpo = { name: file.name, content_b64: await archivoABase64(file) };
    if (reglas) cuerpo.rules = JSON.parse(await reglas.text());
    const d = await api("destination", cuerpo);
    pensando(null);
    await pintarDestinos(d.key);
    if (estado.subida) await proponer();
    toast(`Destino ${d.name} (${d.label}) listo: ${d.targets.length} campos`);
  } catch (e) { pensando(null); toast(e.message); }
}

// ---------- Destino a medida: formato + lista de campos (editor en campos.js) ----------
async function pintarFormatos() {
  await pintarBotonesFormato($("formatos-directos"), elegirFormato);
}

async function elegirFormato(formato) {
  const antes = estado.directo;
  estado.directo = { formato, campos: antes ? antes.campos : [], desde: antes && antes.desde, clave: antes && antes.clave };
  pintarDirecto();
  // Otro formato con la misma lista: se conservan los cambios; un archivo nuevo trae sus campos
  if ($("todos-campos").checked && estado.subida && estado.directo.desde !== estado.subida.upload_id) return camposDelOrigen();
  if (!estado.directo.campos.length) {
    if (!$("todos-campos").checked) anadirCampo();
    $("nombre-destino").textContent = `${FORMATOS[formato] || formato} · ${estado.subida ? "añade campos" : "todos los campos del archivo"}`;
    $("contexto-destino").textContent = estado.subida ? "Escribe los campos que quieres y pulsa «Aplicar»"
      : "Sube o elige unos datos de origen: sus campos aparecerán aquí";
    return;
  }
  await aplicarCampos();
}

async function camposDelOrigen() {
  try {
    const r = await api("fields", { upload_id: estado.subida.upload_id });
    estado.directo.campos = r.fields.map(f => ({ ...f, incluir: true }));
    estado.directo.desde = estado.subida.upload_id;
    await aplicarCampos();
  } catch (e) { toast(e.message); }
}

function anadirCampo() {
  estado.directo.campos.push(campoNuevo());
  pintarDirecto();
  enfocarUltimoCampo($("tabla-campos"));
}

async function aplicarCampos(guardarComo) {
  const d = estado.directo;
  const usados = d.campos.filter(c => c.incluir && c.name.trim());
  if (!usados.length) { toast("Marca o añade al menos un campo"); pintarDirecto(); return; }
  try {
    pensando(guardarComo ? "Guardando el formato…" : "Preparando el destino…");
    const cuerpo = { format: d.formato, fields: camposParaEnviar(d.campos) };
    if (estado.subida) cuerpo.upload_id = estado.subida.upload_id;
    if (guardarComo) Object.assign(cuerpo, { save: true, name: guardarComo });
    else if (d.clave && d.clave.startsWith("medida-")) cuerpo.replace = d.clave;   // se sustituye, no se acumulan
    const r = await api("destination/fields", cuerpo);
    d.clave = r.key;
    r.fields.forEach((f, i) => { usados[i].name = f.name; });   // XML: nombres convertidos en etiquetas válidas
    pensando(null);
    await pintarDestinos(r.key);
    pintarDirecto();
    if (guardarComo) toast(`Formato «${r.name}» guardado: lo encontrarás en «Formatos de destino»`);
    if (estado.subida) await proponer();
  } catch (e) { pensando(null); toast((guardarComo ? "No se pudo guardar: " : "No se puede usar esa lista: ") + e.message); pintarDirecto(); }
}

function guardarFormato() {
  const nombre = $("nombre-guardar").value.trim();
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(nombre)) { toast("Nombre: letras, números, - y _ (sin espacios)"); $("nombre-guardar").focus(); return; }
  aplicarCampos(nombre);
}

function contarCampos() {
  $("n-campos").textContent = estado.directo ? estado.directo.campos.filter(c => c.incluir).length : 0;
}

function pintarDirecto() {
  const d = estado.directo;
  marcarFormato($("formatos-directos"), d ? d.formato : null);
  $("sec-campos").classList.toggle("oculto", !d);
  if (!d) return;
  contarCampos();
  $("campos-formato").textContent = `· ${FORMATOS[d.formato] || d.formato}`;
  pintarEditorCampos($("tabla-campos"), d.campos, {
    origen: c => estado.subida && columna(c.from) ? humanoOrigen(columna(c.from)) : null,
    alCambiar: contarCampos,
    vacio: estado.subida ? "Sin campos todavía: añade el primero." : "Sube o elige unos datos de origen y sus campos aparecerán aquí."
  });
}

function marcarTodos(valor) {
  if (!estado.directo) return;
  estado.directo.campos.forEach(c => { c.incluir = valor; });
  pintarDirecto();
}

// ---------- Inicio ----------
async function iniciar() {
  configurarSelector();
  $("btn-confirmar").onclick = confirmar;
  $("btn-reutilizar").onclick = reutilizar;
  $("revisor").oninput = render;
  $("proponente").onchange = proponer;
  $("dl-receta").onclick = () => estado.ultimo && descargar(`receta_${estado.ultimo.recipe.recipe}.json`, JSON.stringify(estado.ultimo.recipe, null, 2), "application/json");
  $("dl-salida").onclick = () => estado.ultimo && descargar(estado.ultimo.output.filename,
    base64ABytes(estado.ultimo.output.content_b64), estado.ultimo.output.mime);
  $("sel-destino").onchange = () => { estado.directo = null; pintarDirecto(); elegirDestino($("sel-destino").value); };
  $("btn-anadir-campo").onclick = anadirCampo;
  $("btn-aplicar-campos").onclick = () => aplicarCampos();
  $("btn-guardar-formato").onclick = guardarFormato;
  $("btn-todos-marcar").onclick = () => marcarTodos(true);
  $("btn-ninguno-marcar").onclick = () => marcarTodos(false);
  $("todos-campos").onchange = () => {
    if (estado.directo && $("todos-campos").checked && estado.subida) camposDelOrigen();
  };
  $("file-destino").addEventListener("change", e => e.target.files.length && subirDestino(e.target.files));
  try { $("revisor").value = localStorage.getItem("multibridge.revisor") || ""; } catch { /* sin almacenamiento */ }
  $("revisor").addEventListener("change", () => { try { localStorage.setItem("multibridge.revisor", $("revisor").value.trim()); } catch { /* */ } });

  try {
    const q0 = new URLSearchParams(location.search);
    await pintarDestinos(q0.get("destino"));
    await pintarFormatos();
    pintarEjemplos(await api("examples"));
    const salud = await api("health");
    const opciones = $("proponente").options;
    for (const op of opciones) {
      if (op.value !== "rules" && !salud.ollama[op.value]) { op.disabled = true; op.textContent += " — no disponible"; }
    }
    $("estado-ia").textContent = Object.values(salud.ollama).some(Boolean) ? "La IA corre en este equipo (Ollama, 127.0.0.1)"
      : "Ollama no está en marcha: solo reglas";
    const q = new URLSearchParams(location.search);
    if (q.has("ejemplo")) cargarEjemplo(q.get("ejemplo"));
  } catch (e) {
    toast("No se puede hablar con la API local: " + e.message);
  }
  render();
}

iniciar();
