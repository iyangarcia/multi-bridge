// Editor de una lista de campos (un formato de destino sin ejemplo). Lo usan «Traducir datos» y
// «Formatos de destino». Solo pinta y guarda en el array que recibe; quien lo usa decide cuándo aplicarlo.

const TIPOS = { string: "Texto", integer: "Entero", number: "Número", date: "Fecha", boolean: "Sí / No" };
const ORDEN_FORMATOS = ["json", "csv", "excel", "xml"];

// Formatos que sirven sin ejemplo, en un orden fijo
async function formatosSinEjemplo() {
  return (await api("formats")).filter(f => f.blank)
    .sort((a, b) => (ORDEN_FORMATOS.indexOf(a.name) + 1 || 99) - (ORDEN_FORMATOS.indexOf(b.name) + 1 || 99));
}

// Botones de formato en `cont`; `elegir(nombre)` al pulsar uno
async function pintarBotonesFormato(cont, elegir) {
  const lista = await formatosSinEjemplo();
  cont.innerHTML = "";
  lista.forEach(f => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "boton secundario pequeno";
    b.dataset.formato = f.name;
    b.textContent = f.label;
    b.title = `Salida en ${f.label} (${f.extension}) con los campos que elijas`;
    b.onclick = () => elegir(f.name);
    cont.appendChild(b);
  });
}

function marcarFormato(cont, nombre) {
  cont.querySelectorAll("button").forEach(b => b.classList.toggle("activo", b.dataset.formato === nombre));
}

const campoNuevo = () => ({ name: "", type: "string", required: false, multiple: null, from: null, incluir: true, nuevo: true });

// campos: [{ name, type, required, multiple, from, incluir, nuevo }]
// opciones.origen(campo) → { nombre, tecnico } de la columna de la que sale, o null
// opciones.alCambiar() tras marcar / quitar (para contadores)
function pintarEditorCampos(tabla, campos, opciones = {}) {
  const origen = opciones.origen || (() => null);
  const conOrigen = campos.some(c => c.from);
  if (!campos.length) {
    tabla.innerHTML = `<p class="pista">${esc(opciones.vacio || "Sin campos todavía: añade el primero.")}</p>`;
    return;
  }
  tabla.classList.toggle("sin-origen", !conOrigen);
  tabla.innerHTML = `<div class="fila-campo cab"><span>Recibir</span><span>Nombre en la salida</span><span>Tipo</span><span>Obligatorio</span><span>${conOrigen ? "Sale de" : ""}</span><span></span></div>`;
  campos.forEach((c, i) => {
    const fila = document.createElement("div");
    fila.className = "fila-campo" + (c.incluir ? "" : " apagado");
    const o = c.from ? origen(c) : null;
    fila.innerHTML = `
      <span><input type="checkbox" class="incluir" ${c.incluir ? "checked" : ""} aria-label="Recibir este campo"></span>
      <span><input type="text" class="nombre-campo" value="${esc(c.name)}" placeholder="nombre_del_campo" maxlength="200" aria-label="Nombre en la salida"></span>
      <span><select class="tipo-campo" aria-label="Tipo">${Object.entries(TIPOS).map(([k, v]) => `<option value="${k}" ${k === c.type ? "selected" : ""}>${v}</option>`).join("")}</select></span>
      <span><input type="checkbox" class="obligatorio" ${c.required ? "checked" : ""} aria-label="Obligatorio"></span>
      <span class="origen-campo" title="${esc(o ? o.tecnico : "")}">${o ? esc(o.nombre) + (c.multiple === "list" ? ' <i class="pista">· varios valores</i>' : "")
        : conOrigen ? '<i class="pista">nuevo · se propone por su nombre</i>' : (c.multiple === "list" ? '<i class="pista">varios valores</i>' : "")}</span>
      <span>${c.nuevo || opciones.quitarTodos ? '<button type="button" class="boton secundario pequeno quitar-campo" title="Quitar este campo" aria-label="Quitar este campo">×</button>' : ""}</span>`;
    fila.querySelector(".incluir").onchange = e => {
      c.incluir = e.target.checked;
      fila.classList.toggle("apagado", !c.incluir);
      if (opciones.alCambiar) opciones.alCambiar();
    };
    fila.querySelector(".nombre-campo").oninput = e => { c.name = e.target.value; };
    fila.querySelector(".tipo-campo").onchange = e => { c.type = e.target.value; };
    fila.querySelector(".obligatorio").onchange = e => { c.required = e.target.checked; };
    const quitarBtn = fila.querySelector(".quitar-campo");
    if (quitarBtn) quitarBtn.onclick = () => { campos.splice(i, 1); pintarEditorCampos(tabla, campos, opciones); if (opciones.alCambiar) opciones.alCambiar(); };
    tabla.appendChild(fila);
  });
}

function enfocarUltimoCampo(tabla) {
  const entradas = tabla.querySelectorAll("input.nombre-campo");
  if (entradas.length) entradas[entradas.length - 1].focus();
}

// Lo que se manda a la API: solo los campos marcados y con nombre
const camposParaEnviar = campos => campos.filter(c => c.incluir && c.name.trim()).map(c => ({
  name: c.name.trim(), type: c.type, required: !!c.required, multiple: c.multiple || null, from: c.from || null }));
