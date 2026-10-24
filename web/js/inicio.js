// Inicio: hospitales → Multi Bridge → tu aplicación, y las recetas aprobadas (de recipes/, vía la API local).

async function pintarInicio() {
  let destino = null, recetas = [];
  try {
    [destino, recetas] = await Promise.all([api("expected"), api("recipes")]);
  } catch (e) {
    toast("No se puede hablar con la API local: " + e.message);
  }
  $("p-cargando")?.remove();
  const conectado = h => recetas.some(r => r.file === h.archivo);

  const n = HOSPITALES_DEMO.filter(conectado).length;
  $("p-resumen").textContent = `${n} de ${HOSPITALES_DEMO.length} hospitales de ejemplo conectados · ${recetas.length} receta(s)`;

  const cont = $("p-hospitales");
  cont.innerHTML = "";
  HOSPITALES_DEMO.forEach(h => {
    const ok = conectado(h);
    const a = document.createElement("a");
    a.className = "hospital" + (ok ? " conectado" : "");
    a.href = `mapeador.html?ejemplo=${encodeURIComponent(h.archivo)}`;
    a.innerHTML = `
      <span class="hospital-icono">${ok ? ICONO.check(22) : ICONO.hospital(22)}</span>
      <span class="hospital-texto"><strong></strong><small></small></span>
      <span class="formato-insignia">${h.formato}</span>`;
    a.querySelector("strong").textContent = h.corto;
    a.querySelector("small").textContent = ok ? `${h.ciudad} · conectado` : h.ciudad;
    cont.appendChild(a);
  });
  const nuevo = document.createElement("a");
  nuevo.className = "hospital nuevo";
  nuevo.href = "mapeador.html";
  nuevo.innerHTML = `<span class="hospital-icono">+</span><span class="hospital-texto"><strong>Otro hospital</strong><small>Sube su archivo</small></span>`;
  cont.appendChild(nuevo);

  const app = $("p-app");
  const grupos = destino ? agruparPorGrupo(destino.targets) : [];
  app.innerHTML = `
    <div class="app-cab"><img src="img/icono.png" alt=""><span class="formato-insignia">JSON</span></div>
    <h3>Datos listos para tu aplicación</h3>
    <p>${destino ? esc(destino.name) : "Sin formato"}</p>
    <div class="grupos-mini">${grupos.map(([g, campos]) =>
      `<div class="grupo-mini">${iconoGrupo(g, 18)}${esc(nombreGrupo(g))}<span>${campos.length} datos</span></div>`).join("")}</div>
    <a class="enlace" href="modelos.html">Ver el formato completo</a>`;

  pintarRecetas(recetas);
  requestAnimationFrame(dibujarCables);
}

function pintarRecetas(recetas) {
  const cont = $("p-actividad");
  if (!recetas.length) {
    cont.innerHTML = `<div class="vacio-actividad">Todavía no hay recetas. Cuando apruebes una conexión aparecerá aquí.</div>`;
    return;
  }
  cont.innerHTML = `<table class="actividad"><thead><tr><th>Archivo</th><th>Formato</th><th>Datos</th><th>Aprobada por</th><th>Fecha</th><th></th></tr></thead><tbody></tbody></table>`;
  [...recetas].sort((a, b) => b.at.localeCompare(a.at)).forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><b></b></td><td><span class="formato-insignia"></span></td><td>${r.mapped} de ${r.total}</td>
      <td></td><td class="gris"></td><td><button type="button" class="boton secundario pequeno">Descargar</button></td>`;
    const demo = HOSPITALES_DEMO.find(h => h.archivo === r.file);
    tr.querySelector("b").textContent = demo ? `${demo.nombre} (${demo.ciudad})` : r.file;
    tr.querySelector(".formato-insignia").textContent = FORMATOS[r.format] || r.format;
    tr.children[3].textContent = r.approved_by;
    tr.children[4].textContent = new Date(r.at).toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" });
    const dl = tr.querySelector("button");
    dl.setAttribute("aria-label", `Descargar la receta ${r.name}`);
    dl.onclick = async () => descargar(`receta_${r.name}.json`, JSON.stringify(await api(`recipes/${encodeURIComponent(r.name)}`), null, 2), "application/json");
    cont.querySelector("tbody").appendChild(tr);
  });
}

// Cables animados: cada hospital → puente → tu aplicación
function dibujarCables() {
  const lienzo = $("cables"), base = $("diagrama").getBoundingClientRect();
  if (getComputedStyle(lienzo).display === "none") return;
  const icono = document.querySelector(".puente-icono").getBoundingClientRect();
  const app = $("p-app").getBoundingClientRect();
  const x = v => v - base.left, y = v => v - base.top;
  const curva = (x1, y1, x2, y2) => { const m = (x1 + x2) / 2; return `M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}`; };
  const cy = y(icono.top + icono.height / 2);
  let html = "";
  document.querySelectorAll("#p-hospitales .hospital:not(.nuevo)").forEach(h => {
    const r = h.getBoundingClientRect();
    const d = curva(x(r.right), y(r.top + r.height / 2), x(icono.left) - 8, cy);
    html += `<path class="cable" d="${d}"/><path class="cable vivo${h.classList.contains("conectado") ? " conectado" : ""}" d="${d}"/>`;
  });
  const d = curva(x(icono.right) + 8, cy, x(app.left), cy);
  html += `<path class="cable" d="${d}"/><path class="cable vivo" d="${d}"/>`;
  lienzo.innerHTML = html;
}
window.addEventListener("resize", dibujarCables);
document.fonts && document.fonts.ready.then(dibujarCables);

pintarInicio();
