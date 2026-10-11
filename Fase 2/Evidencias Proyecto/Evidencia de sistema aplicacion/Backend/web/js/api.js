/* Comunicación con la API. El token de sesión se guarda en sessionStorage
   (se borra al cerrar la pestaña). */
const Sesion = {
  get token() { try { return sessionStorage.getItem("qla_token"); } catch { return null; } },
  get usuario() { try { return JSON.parse(sessionStorage.getItem("qla_usuario") || "null"); } catch { return null; } },
  guardar(token, usuario) {
    try { sessionStorage.setItem("qla_token", token); sessionStorage.setItem("qla_usuario", JSON.stringify(usuario)); } catch {}
  },
  actualizarUsuario(usuario) { try { sessionStorage.setItem("qla_usuario", JSON.stringify(usuario)); } catch {} },
  cerrar() { try { sessionStorage.removeItem("qla_token"); sessionStorage.removeItem("qla_usuario"); } catch {} },
};

class ErrorApi extends Error {
  constructor(estado, mensaje) { super(mensaje); this.estado = estado; }
}

function textoError(detalle) {
  if (!detalle) return "Error inesperado";
  if (typeof detalle === "string") return detalle;
  if (Array.isArray(detalle)) {
    return detalle.map((d) => {
      const campo = (d.loc || []).filter((x) => x !== "body").join(".");
      return campo ? `${campo}: ${d.msg}` : d.msg;
    }).join(". ");
  }
  return "Error inesperado";
}

async function api(ruta, { metodo = "GET", cuerpo = null, params = null } = {}) {
  let url = "/api" + ruta;
  if (params) {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") q.set(k, v); });
    if ([...q].length) url += "?" + q.toString();
  }
  const cabeceras = { "Accept": "application/json" };
  if (cuerpo) cabeceras["Content-Type"] = "application/json";
  if (Sesion.token) cabeceras["Authorization"] = "Bearer " + Sesion.token;

  let resp;
  try {
    resp = await fetch(url, { method: metodo, headers: cabeceras, body: cuerpo ? JSON.stringify(cuerpo) : null });
  } catch {
    throw new ErrorApi(0, "No se pudo conectar con el servidor. Revise que la API esté en ejecución.");
  }
  let datos = null;
  try { datos = await resp.json(); } catch {}
  if (!resp.ok) {
    if (resp.status === 401 && !ruta.startsWith("/auth/login")) {
      Sesion.cerrar();
      window.location.replace("/login.html?motivo=sesion");
    }
    throw new ErrorApi(resp.status, textoError(datos && datos.detail));
  }
  return datos;
}

/* Formatos en hora de Chile */
const ZONA = "America/Santiago";
const fmtFechaHora = new Intl.DateTimeFormat("es-CL", { timeZone: ZONA, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtHora = new Intl.DateTimeFormat("es-CL", { timeZone: ZONA, hour: "2-digit", minute: "2-digit" });
const fmtDiaHora = new Intl.DateTimeFormat("es-CL", { timeZone: ZONA, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
function fechaHora(iso) { return iso ? fmtFechaHora.format(new Date(iso)) : "—"; }
function numero(v, dec = 2) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("es-CL", { maximumFractionDigits: dec });
}

/* Construye elementos sin usar innerHTML (evita inyección de código desde los datos). */
function el(etiqueta, atributos = {}, ...hijos) {
  const e = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(atributos || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "clase") e.className = v;
    else if (k === "texto") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) {
    if (h === null || h === undefined || h === false) continue;
    e.append(h instanceof Node ? h : document.createTextNode(String(h)));
  }
  return e;
}
