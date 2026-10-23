// «Formatos de destino»: lista de destinos, ficha del elegido, y crear / editar / eliminar formatos hechos
// con una lista de campos (editor en campos.js). Todo pasa por la API local; aquí solo se pinta.

const est = {
  lista: [],        // GET /api/destinations
  clave: null,      // destino que se ve
  editor: null      // { clave (al editar), formato, campos }
};

const ORIGENES = { carpeta: "En la carpeta", ejemplo: "Ejemplo", guardado: "Creado aquí", subido: "Subido", medida: "A medida" };

// ---------- Lista ----------
async function pintarLista(elegido) {
  est.lista = await api("destinations");
  const clave = est.lista.some(d => d.key === elegido) ? elegido : est.clave && est.lista.some(d => d.key === est.clave) ? est.clave
    : (est.lista[0] || {}).key;
  $("lista-formatos").innerHTML = est.lista.map(d => `
    <button type="button" class="tarjeta-formato${d.key === clave ? " activa" : ""}" data-clave="${esc(d.key)}">
      <span class="tf-formato">${esc(d.label)}</span>
      <strong>${esc(d.name)}</strong>
      <small>${d.fields} campos · ${esc(ORIGENES[d.origin] || d.origin)}</small>
    </button>`).join("") || `<p class="pista">No hay formatos todavía: crea el primero.</p>`;
  $("lista-formatos").querySelectorAll(".tarjeta-formato").forEach(b => { b.onclick = () => verFormato(b.dataset.clave); });
  if (clave) await verFormato(clave);
}

async function verFormato(clave) {
  try {
    const d = await api("expected?destination=" + encodeURIComponent(clave));
    est.clave = clave;
    history.replaceState(null, "", "?destino=" + encodeURIComponent(clave));
    document.querySelectorAll(".tarjeta-formato").forEach(b => b.classList.toggle("activa", b.dataset.clave === clave));
    const info = est.lista.find(x => x.key === clave) || {};
    $("vista-modelo").classList.remove("oculto");
    $("v-nombre").textContent = d.name;
    $("v-sub").textContent = [`${d.label} · ${d.targets.length} campos`, ORIGENES[info.origin] || "",
      info.editable ? "hecho con una lista de campos" : info.origin === "subido" || info.origin === "carpeta" || info.origin === "ejemplo" ? "definido con un ejemplo" : "",
      d.pack ? `vocabulario: ${d.pack}` : "", d.group_by ? `agrupa por ${d.group_by}` : ""].filter(Boolean).join(" · ");
    $("v-formato").textContent = d.label;
    $("v-id").textContent = d.id;
    $("btn-usar").href = "mapeador.html?destino=" + encodeURIComponent(clave);
    $("btn-editar").classList.toggle("oculto", !info.editable);
    $("btn-eliminar").classList.toggle("oculto", !(info.editable || info.origin === "subido"));
    $("v-campos").innerHTML = agruparPorGrupo(d.targets).map(([g, campos]) => `
      <div class="grupo-modelo">
        <div class="grupo-modelo-cab"><span class="g-icono">${iconoGrupo(g, 20)}</span><strong>${esc(nombreGrupo(g))}</strong><small>${campos.length} datos</small></div>
        ${campos.map(t => {
          const h = humanoDestino(t);
          const reglas = [t.enum ? `valores: ${t.enum.join(", ")}` : "", t.unit ? `en ${t.unit}` : ""].filter(Boolean).join(" · ");
          const muestra = t.example !== null && t.example !== undefined ? formatear(t.example) : TIPOS[t.type] || t.type;
          return `<div class="dato" title="${esc(h.ayuda + (reglas ? " · " + reglas : ""))}"><span>${esc(h.nombre)}${t.required ? '<i class="imprescindible-punto" title="Imprescindible"></i>' : ""}</span><b>${esc(muestra)}</b></div>`;
        }).join("")}
      </div>`).join("");
  } catch (e) { toast("No se puede abrir ese formato: " + e.message); }
}

// ---------- Editor ----------
function abrirEditor(editor) {
  est.editor = editor;
  $("editor").classList.remove("oculto");
  $("editor-titulo").textContent = editor.clave ? `Editar «${editor.nombre}»` : "Nuevo formato";
  $("e-nombre").value = editor.nombre || "";
  $("e-desde-ejemplo").value = "";
  marcarFormato($("e-formatos"), editor.formato);
  pintarEditor();
  $("editor").scrollIntoView({ behavior: "smooth", block: "start" });
  $("e-nombre").focus();
}

function pintarEditor() {
  pintarEditorCampos($("e-campos"), est.editor.campos, { quitarTodos: true,
    vacio: "Sin campos todavía: añade el primero o empieza con los de un archivo." });
}

function crear() {
  abrirEditor({ clave: null, nombre: "", formato: "json", campos: [campoNuevo()] });
}

async function editar() {
  try {
    const f = await api("destination/fields?destination=" + encodeURIComponent(est.clave));
    abrirEditor({ clave: f.key, guardado: f.saved, nombre: f.saved ? f.name : "", formato: f.format,
      campos: f.fields.map(c => ({ ...c, incluir: true })) });
  } catch (e) { toast(e.message); }
}

function cerrarEditor() {
  est.editor = null;
  $("editor").classList.add("oculto");
}

async function camposDe(subida) {
  const r = await api("fields", { upload_id: subida.upload_id });
  // Solo nombres y tipos: aquí no se ata cada campo a una columna (eso es de cada traducción)
  est.editor.campos = r.fields.map(f => ({ name: f.name, type: f.type, required: false, multiple: f.multiple,
    from: null, incluir: true }));
  pintarEditor();
  toast(`${r.fields.length} campos tomados de ${subida.name}: cambia lo que quieras y guarda`);
}

async function desdeEjemplo(nombre) {
  if (!nombre) return;
  try { await camposDe(await api("upload", { example: nombre })); } catch (e) { toast(e.message); }
}

async function desdeArchivo(file) {
  try { await camposDe(await api("upload", { name: file.name, content_b64: await archivoABase64(file) })); }
  catch (e) { toast("No se pudo leer el archivo: " + e.message); }
}

async function guardar() {
  const ed = est.editor;
  const nombre = $("e-nombre").value.trim();
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(nombre)) { toast("Nombre: letras, números, - y _ (sin espacios)"); $("e-nombre").focus(); return; }
  const campos = camposParaEnviar(ed.campos);
  if (!campos.length) { toast("Marca o añade al menos un campo con nombre"); return; }
  try {
    const cuerpo = { format: ed.formato, name: nombre, fields: campos, save: true };
    if (ed.clave && ed.guardado) cuerpo.replace = ed.clave;   // editar (o renombrar) el mismo archivo
    const r = await api("destination/fields", cuerpo);
    if (ed.clave && !ed.guardado) await api("destination/delete", { key: ed.clave });   // uno a medida pasa a guardado
    cerrarEditor();
    await pintarLista(r.key);
    toast(`Formato «${r.name}» guardado`);
  } catch (e) { toast("No se pudo guardar: " + e.message); }
}

async function eliminar() {
  const info = est.lista.find(x => x.key === est.clave);
  if (!info || !confirm(`¿Eliminar el formato «${info.name}»? Las recetas aprobadas para él dejarán de aplicarse.`)) return;
  try {
    await api("destination/delete", { key: est.clave });
    est.clave = null;
    await pintarLista();
    toast(`Formato «${info.name}» eliminado`);
  } catch (e) { toast(e.message); }
}

// ---------- Subir un ejemplo de la salida ----------
async function subirEjemplo(files) {
  const lista = [...files];
  const reglas = lista.find(f => f.name.toLowerCase().endsWith(".rules.json"));
  const file = lista.find(f => f !== reglas);
  if (!file) { toast("Elige el ejemplo de la salida (y, si quieres, su .rules.json)"); return; }
  try {
    const cuerpo = { name: file.name, content_b64: await archivoABase64(file) };
    if (reglas) cuerpo.rules = JSON.parse(await reglas.text());
    const d = await api("destination", cuerpo);
    await pintarLista(d.key);
    toast(`Formato ${d.name} (${d.label}) listo: ${d.targets.length} campos. Se queda en memoria mientras la app esté abierta.`);
  } catch (e) { toast(e.message); }
}

// ---------- Inicio ----------
async function iniciar() {
  $("btn-crear").onclick = crear;
  $("btn-editar").onclick = editar;
  $("btn-eliminar").onclick = eliminar;
  $("btn-cancelar").onclick = cerrarEditor;
  $("e-anadir").onclick = () => { est.editor.campos.push(campoNuevo()); pintarEditor(); enfocarUltimoCampo($("e-campos")); };
  $("e-guardar").onclick = guardar;
  $("e-desde-ejemplo").onchange = e => desdeEjemplo(e.target.value);
  $("e-desde-archivo").addEventListener("change", e => e.target.files[0] && desdeArchivo(e.target.files[0]));
  $("file-ejemplo").addEventListener("change", e => e.target.files.length && subirEjemplo(e.target.files));
  try {
    await pintarBotonesFormato($("e-formatos"), f => { est.editor.formato = f; marcarFormato($("e-formatos"), f); });
    const ejemplos = await api("examples");
    $("e-desde-ejemplo").innerHTML = `<option value="">un ejemplo sintético…</option>` +
      ejemplos.map(e => { const x = describirEjemplo(e.name); return `<option value="${esc(e.name)}">${esc(x.nombre)} · ${esc(x.formato)}</option>`; }).join("");
    const q = new URLSearchParams(location.search);
    await pintarLista(q.get("destino"));
    if (q.has("crear")) crear();
  } catch (e) {
    toast("No se puede hablar con la API local: " + e.message);
  }
}

iniciar();
