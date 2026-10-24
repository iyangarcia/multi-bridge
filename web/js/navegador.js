// Web worker de la demo de GitHub Pages: el mismo Python de multibridge, ejecutado en el navegador
// (Pyodide). comun.js le manda cada llamada a la API y esto responde lo que respondería el servidor
// local (multibridge/browser.py). Los archivos de la persona no salen de su equipo: aquí solo se
// descargan Pyodide (CDN) y el paquete de esta misma web (scripts/build_pages.py).
// Recetas y formatos guardados viven en IndexedDB (IDBFS), por navegador.

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";   // Python 3.13: PYODIDE_PYTHON en build_pages.py
const RAIZ = "/home/pyodide/mb";

importScripts(PYODIDE + "pyodide.js");

const sincronizar = (py, cargar) => new Promise((ok, mal) => py.FS.syncfs(cargar, e => e ? mal(e) : ok()));

async function arrancar() {
  const base = new URL("../demo/", self.location);
  const manifiesto = await (await fetch(new URL("manifest.json", base), { cache: "no-cache" })).json();
  const [py, paquete] = await Promise.all([
    loadPyodide({ indexURL: PYODIDE }),
    fetch(new URL(manifiesto.package, base)).then(r => r.arrayBuffer())
  ]);
  for (const carpeta of ["recipes", "expected"]) {
    py.FS.mkdirTree(`${RAIZ}/${carpeta}`);
    py.FS.mount(py.FS.filesystems.IDBFS, {}, `${RAIZ}/${carpeta}`);
  }
  await sincronizar(py, true);
  // los destinos de ejemplo vienen siempre del paquete; las listas de campos guardadas se quedan
  py.runPython(`
from pathlib import Path
for p in Path("${RAIZ}/expected").iterdir():
    if not p.name.endswith(".fields.json"):
        p.unlink()
`);
  py.unpackArchive(paquete, "zip", { extractDir: RAIZ });   // multibridge, openpyxl, ejemplos
  py.runPython(`import sys; sys.path.insert(0, "${RAIZ}")`);
  const browser = py.pyimport("multibridge.browser");
  browser.start(RAIZ);
  return { py, browser };
}

const listo = arrancar();

self.onmessage = async ({ data: { id, metodo, ruta, cuerpo } }) => {
  try {
    const { py, browser } = await listo;
    const respuesta = JSON.parse(browser.call(metodo, "/api/" + ruta, cuerpo === undefined ? null : JSON.stringify(cuerpo)));
    if (respuesta.saved) await sincronizar(py, false);
    self.postMessage({ id, respuesta });
  } catch (e) {
    self.postMessage({ id, respuesta: { status: 0, error: "no se pudo arrancar Python en el navegador: " + (e.message || e) } });
  }
};
