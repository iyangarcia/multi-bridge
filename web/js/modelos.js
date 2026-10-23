// "Destinos": ficha de un destino, leída de su ejemplo a través de la API local (solo lectura).

async function pintarFormato() {
  try {
    const clave = new URLSearchParams(location.search).get("destino");
    const d = await api("expected" + (clave ? "?destination=" + encodeURIComponent(clave) : ""));
    $("v-formato").textContent = d.label;
    $("v-nombre").textContent = d.name;
    $("v-id").textContent = d.id;
    $("v-campos").innerHTML = agruparPorGrupo(d.targets).map(([g, campos]) => `
      <div class="grupo-modelo">
        <div class="grupo-modelo-cab"><span class="g-icono">${iconoGrupo(g, 20)}</span><strong>${esc(nombreGrupo(g))}</strong><small>${campos.length} datos</small></div>
        ${campos.map(t => {
          const h = humanoDestino(t);
          const reglas = [t.enum ? `valores: ${t.enum.join(", ")}` : "", t.unit ? `en ${t.unit}` : ""].filter(Boolean).join(" · ");
          return `<div class="dato" title="${esc(h.ayuda + (reglas ? " · " + reglas : ""))}"><span>${esc(h.nombre)}${t.required ? '<i class="imprescindible-punto" title="Imprescindible"></i>' : ""}</span><b>${esc(formatear(t.example))}</b></div>`;
        }).join("")}
      </div>`).join("");
  } catch (e) {
    toast("No se puede hablar con la API local: " + e.message);
  }
}

pintarFormato();
