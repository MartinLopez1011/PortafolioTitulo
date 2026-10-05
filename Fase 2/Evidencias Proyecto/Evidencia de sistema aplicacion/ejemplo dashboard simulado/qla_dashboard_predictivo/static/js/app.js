/* Química Latinoamericana: monitor y mantenimiento predictivo del molino coloidal MC-01 */
"use strict";

const $ = (id) => document.getElementById(id);
const S = { info: null, ultimo: null, buf: null, MAX: 2000, predHist: [], reproduciendo: true, ocupado: false,
            vista: "proceso", ticks: 0, escenarios: [] };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const MARCHA = ["Produccion", "Limpieza"];
const COLOR_FALLA = { Sobrecarga_Motor_Por_Asfalto_Frio: "#C62D1F", Filtro_Obstruido: "#1F5FA8", Advertencia_Radar_Sucio_Betun: "#6A3D9A" };
const CLASE_HZ = { "24 h": "riesgo-alto", "5 días": "riesgo-medio", "15 días": "riesgo-bajo-15" };
const OPERACION = { Produccion: "Producción", Limpieza: "Limpieza de línea", Espera: "En espera", Preparacion: "Preparación",
                    Detenida: "Detenida", Mantenimiento: "Mantenimiento" };

// ------------------------------------------------------------------ utilidades
function num(v, dec) {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  if (dec === undefined) dec = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : 2;
  return Number(v).toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
const hora = (iso) => (iso ? iso.slice(11, 16) : "--:--");
const fecha = (iso) => (iso ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : "");
const minutosEntre = (a, b) => Math.round((new Date(b) - new Date(a)) / 60000);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sensor = (id) => S.info.sensores.find((s) => s.id === id) || { nombre: id, unidad: "", equipo: "" };
const fuera = (id, v) => { const b = S.ultimo?.banda?.[id]; return b ? v < b[0] - 1e-9 || v > b[1] + 1e-9 : false; };
const titulo = (estado) => S.info.fallas[estado]?.titulo || estado;
const operador = () => $("operador").value.trim() || "Operador";

async function api(url, op = {}) {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...op, body: op.body ? JSON.stringify(op.body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Error del servidor");
  return d;
}

function valorTexto(id, v) {
  if (id === "POS_valvula_3vias") return v >= 0.5 ? "Agua" : "Asfalto";
  if (id === "VAL_aire_linea") return v >= 0.5 ? "Abierta" : "Cerrada";
  if (id === "EST_niv_betum_dep") return v >= 0.5 ? "Falla" : "OK";
  return `${num(v)} ${sensor(id).unidad}`;
}

// ------------------------------------------------------------------ inicio
async function iniciar() {
  S.info = await api("/api/info");
  $("nombre-equipo").textContent = S.info.equipo;
  $("nombre-planta").textContent = `${S.info.empresa}: ${S.info.planta}`;
  const m = S.info.modelos;
  $("chip-modelos").textContent = `Modelos: ${[m.identificacion && "identificación", m.autoencoder && "autoencoder", m.prediccion && "predicción"].filter(Boolean).join(", ") || "ninguno"}`;
  $("id-nombre").textContent = `Identificación de fallas (${m.identificacion || "no cargado"})`;
  if (m.umbral_ae) $("ae-umbral").style.left = `${posLog(m.umbral_ae)}%`;
  $("persistencia").textContent = `se activan con ${S.info.persistencia[0]} de ${S.info.persistencia[1]} minutos`;
  try { $("operador").value = localStorage.getItem("qla-operador") || ""; } catch (e) { /* sin almacenamiento */ }
  $("operador").addEventListener("change", () => { try { localStorage.setItem("qla-operador", $("operador").value); } catch (e) {} });

  construirGauges();
  construirMinis();
  prepararTabs();
  prepararControles();
  prepararMantenimiento();
  await cargarEscenarios();
  prepararEditor();
  $("sensor-tendencia").innerHTML = S.info.sensores.map((s) => `<option value="${s.id}">${esc(s.nombre)} (${s.equipo})</option>`).join("");
  $("sensor-tendencia").value = "AMP_vfd_motor_molino";
  $("sensor-tendencia").onchange = renderTendencias;
  await tick();
  setInterval(() => { if (S.reproduciendo) tick(); }, 1000);
}

// ------------------------------------------------------------------ ciclo
function reiniciarBuffers() { S.buf = null; S.predHist = []; }

async function tick() {
  if (S.ocupado) return;
  S.ocupado = true;
  try {
    const d = await api(`/api/paso?n=${$("velocidad").value}`, { method: "POST" });
    S.ultimo = d;
    if (!S.buf) S.buf = Object.fromEntries(Object.keys(d.serie).map((k) => [k, []]));
    for (const k of Object.keys(d.serie)) {
      S.buf[k].push(...d.serie[k]);
      if (S.buf[k].length > S.MAX) S.buf[k].splice(0, S.buf[k].length - S.MAX);
    }
    if (d.prediccion && S.predHist.at(-1)?.tiempo !== d.prediccion.tiempo) {
      S.predHist.push(d.prediccion);
      if (S.predHist.length > 24 * 40) S.predHist.shift();
    }
    S.ticks++;
    render();
  } catch (e) {
    $("chip-operacion").innerHTML = `<span class="punto off"></span>Sin conexión con el servidor`;
  } finally { S.ocupado = false; }
}

function render() {
  const d = S.ultimo;
  $("reloj").innerHTML = `${hora(d.tiempo)}<small>${fecha(d.tiempo)}</small>`;
  const enMarcha = MARCHA.includes(d.operacion);
  const tipo = d.tipo === "Ninguno" ? "" : `, ${d.tipo === "Plastomerico" ? "plastomérico" : "convencional"}`;
  $("chip-operacion").innerHTML = `<span class="punto ${enMarcha ? "ok" : ""}"></span>${OPERACION[d.operacion] || d.operacion}${tipo}`;
  $("modo-operacion").textContent = `${OPERACION[d.operacion] || d.operacion}${tipo}`;
  const f = d.fuente;
  const real = d.etiqueta_real.startsWith("Simulado") ? d.etiqueta_real : `Etiqueta real: ${titulo(d.etiqueta_real)}`;
  const modo = f.modo ? `Modo demostración: ${$("funcionamiento").selectedOptions[0]?.textContent}. ` : "Reproducción del año 2026. ";
  $("nota-control").textContent = f.escenario
    ? `${modo}Falla inyectada: ${f.escenario}, desarrollo ${Math.round(100 * f.progreso)} %.`
    : f.modo ? `${modo}Datos reales de ese modo de operación, en bucle.` : `${modo}${real}`;
  renderAnunciador(); renderEsquema(); renderGauges(); renderDiagnostico(); renderAlarmasActivas(); renderRiesgoResumen(); renderMinis(); renderKpis();
  $("insignia-alarmas").hidden = d.alarmas.length === 0; $("insignia-alarmas").textContent = d.alarmas.length;
  const nRiesgo = (d.prediccion?.filas || []).filter((x) => x.nivel === "24 h" || x.nivel === "5 días").length;
  $("insignia-riesgo").hidden = nRiesgo === 0; $("insignia-riesgo").textContent = nRiesgo;
  if (S.vista === "prediccion") renderPrediccion();
  if (S.vista === "tendencias") renderTendencias();
  if (S.vista === "alarmas" && S.ticks % 3 === 0) cargarAlarmas();
  if (S.vista === "salud" && S.ticks % 15 === 0) cargarSalud();
  if (S.vista === "mantenimiento" && S.ticks % 5 === 0) cargarMantenimiento();
}

// ------------------------------------------------------------------ anunciador
function renderAnunciador() {
  const d = S.ultimo, an = $("anunciador");
  const a = d.alarmas.find((x) => x.tipo === "modelo" && x.prioridad === "alta") || d.alarmas.find((x) => x.prioridad === "alta") || d.alarmas[0];
  if (!a) {
    an.className = "anunciador normal";
    const marcha = MARCHA.includes(d.operacion);
    const TIT = { Detenida: "Molino detenido", Espera: "Molino en espera", Preparacion: "Preparación de la línea", Mantenimiento: "Mantenimiento en curso" };
    $("an-titulo").textContent = marcha ? "Operación normal" : TIT[d.operacion] || "Molino detenido";
    const riesgo = (d.prediccion?.filas || []).filter((x) => x.nivel === "24 h" || x.nivel === "5 días");
    $("an-accion").textContent = riesgo.length
      ? `Sin fallas activas, pero hay riesgo de falla próxima: ${riesgo.map((x) => `${x.nombre} (${x.nivel})`).join(", ")}. Ver Predicción.`
      : marcha ? "Continuar monitoreo." : "Las calderas mantienen la temperatura. Los modelos de diagnóstico se aplican con el molino en marcha.";
    $("an-origen").textContent = marcha ? d.evaluacion.origen : "";
    $("an-tiempo").textContent = "";
    $("an-reconocer").hidden = $("an-detalle").hidden = true;
    return;
  }
  const clave = a.clave.startsWith("modelo:") ? a.clave.slice(7) : null;
  const f = clave ? S.info.fallas[clave] : null;
  an.className = `anunciador ${f ? f.nivel : a.prioridad === "alta" ? "alerta" : "aviso"}`;
  $("an-titulo").textContent = a.titulo;
  $("an-accion").textContent = f ? f.accion : "Límite superado. Verificar el equipo en planta.";
  $("an-origen").textContent = clave && d.evaluacion.estado === clave ? d.evaluacion.origen : a.origen || "";
  $("an-tiempo").textContent = `Activa desde ${hora(a.inicio)} (${fecha(a.inicio)}), hace ${minutosEntre(a.inicio, d.tiempo)} min` +
    (d.alarmas.length > 1 ? `, ${d.alarmas.length} alarmas activas` : "");
  $("an-reconocer").hidden = !!a.reconocida_en;
  $("an-reconocer").onclick = () => reconocer(a.id);
  $("an-detalle").hidden = false;
}

// ------------------------------------------------------------------ esquema del proceso y medidores
const VERDE = "#3FB950", AMBAR = "#F0883E", ROJO = "#F85149", AZUL = "#58A6FF";
const GAUGES_IZQ = [
  { id: "AMP_vfd_motor_molino", t: "Corriente motor", min: 0, max: 160, z: [[0, 120, VERDE], [120, 130, AMBAR], [130, 160, ROJO]] },
  { id: "TOR_vfd_motor_molino", t: "Torque", min: 0, max: 150, z: [[0, 90, VERDE], [90, 105, AMBAR], [105, 150, ROJO]] },
  { id: "VIB_vel_motor_molino", t: "Vibración", min: 0, max: 8, z: [[0, 3.5, VERDE], [3.5, 4.5, AMBAR], [4.5, 8, ROJO]] },
  { id: "RPM_motor_molino", t: "Velocidad", min: 0, max: 3200, z: [[0, 3200, AZUL]] },
  { id: "TEM_emulsion_molino_out", t: "T° salida molino", min: 0, max: 120, z: [[0, 100, VERDE], [100, 110, AMBAR], [110, 120, ROJO]] },
  { id: "CAU_bomba_lpm", t: "Caudal bomba", min: 0, max: 300, z: [[0, 300, AZUL]] },
];
const GAUGES_DER = [
  { id: "TEM_son_betum_in", t: "Temperatura betún", min: 0, max: 220, z: null },
  { id: "TEM_son_solucion_in", t: "Temperatura solución", min: 0, max: 60, z: [[0, 60, AZUL]] },
  { id: "PRE_dif_filtro_bar", t: "ΔP filtro", min: 0, max: 1.6, z: [[0, 0.8, VERDE], [0.8, 1.1, AMBAR], [1.1, 1.6, ROJO]] },
  { id: "PRE_intercambiador_bar", t: "Presión intercambiador", min: 0, max: 5, z: [[0, 3.2, VERDE], [3.2, 3.6, AMBAR], [3.6, 5, ROJO]] },
  { id: "AMP_eco_betum_dep", t: "Eco radar betún", min: 0, max: 80, z: [[0, 23, ROJO], [23, 35, AMBAR], [35, 80, VERDE]] },
  { id: "AE", t: "Índice de salud (AE)", min: 0, max: 2, z: null },
];

function construirGauges() {
  const html = (g) => `<div class="gauge" title="${g.t}"><div class="gauge-titulo">${g.t}</div><svg viewBox="0 0 120 80" id="gz-${g.id}"></svg></div>`;
  $("gauges-izq").innerHTML = GAUGES_IZQ.map(html).join("");
  $("gauges-der").innerHTML = GAUGES_DER.map(html).join("");
}

function arco(f0, f1, r = 46, cx = 60, cy = 64) {
  const p = (f) => [cx + r * Math.cos(Math.PI * (1 - f)), cy - r * Math.sin(Math.PI * (1 - f))];
  const [x0, y0] = p(f0), [x1, y1] = p(f1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function dibujarGauge(g, valor, unidad) {
  let zonas = g.z;
  if (g.id === "TEM_son_betum_in") {
    const lo = S.ultimo.tipo === "Plastomerico" ? 175 : 125;
    zonas = S.ultimo.operacion === "Produccion" ? [[0, lo, ROJO], [lo, lo + 10, AMBAR], [lo + 10, 220, VERDE]] : [[0, 220, AZUL]];
  }
  if (g.id === "AE") {
    const u = S.info.modelos.umbral_ae || 0.5;
    g.max = 4 * u; zonas = [[0, u, VERDE], [u, 2 * u, AMBAR], [2 * u, 4 * u, ROJO]];
  }
  const fr = (v) => Math.min(1, Math.max(0, (v - g.min) / (g.max - g.min)));
  const v = valor ?? 0;
  const col = (zonas.find(([a, b]) => v >= a && v <= b) || zonas[zonas.length - 1])[2];
  $(`gz-${g.id}`).innerHTML =
    zonas.map(([a, b, c]) => `<path d="${arco(fr(a), fr(b))}" stroke="${c}" stroke-width="9" fill="none" opacity=".28"/>`).join("") +
    (fr(v) > 0.001 ? `<path d="${arco(0, fr(v))}" stroke="${col}" stroke-width="9" fill="none" stroke-linecap="butt"/>` : "") +
    `<text class="gauge-valor" x="60" y="62" text-anchor="middle">${valor === null ? "--" : num(v)}</text>
     <text class="gauge-unidad" x="60" y="76" text-anchor="middle">${unidad}</text>`;
}

function renderGauges() {
  const d = S.ultimo;
  [...GAUGES_IZQ, ...GAUGES_DER].forEach((g) => {
    if (g.id === "AE") dibujarGauge(g, d.evaluacion.autoencoder ? d.evaluacion.autoencoder.error : null, d.evaluacion.autoencoder ? "error de reconstrucción" : "molino detenido");
    else dibujarGauge(g, d.lecturas[g.id], sensor(g.id).unidad);
  });
}

function nivel(id, pct, y0, alto) {
  const h = alto * Math.min(1, Math.max(0, pct / 100));
  $(id).setAttribute("y", y0 + alto - h); $(id).setAttribute("height", h);
}

function renderEsquema() {
  const d = S.ultimo, L = d.lecturas, ae = d.evaluacion.autoencoder;
  const senal = new Set(ae?.anomalia ? ae.sensores.map((s) => s.id) : []);
  document.querySelectorAll("#esquema text.val[id^='t-']").forEach((el) => {
    const id = el.id.slice(2);
    if (!(id in L)) return;
    el.textContent = id.startsWith("POR_niv") ? `Nivel ${num(L[id], 0)} %` : valorTexto(id, L[id]);
    el.classList.toggle("fuera", fuera(id, L[id]));
    el.classList.toggle("senalado", senal.has(id));
  });
  for (const g of document.querySelectorAll("#esquema .equipo-g")) {
    const eq = g.id.slice(2), ids = S.info.sensores.filter((s) => s.equipo === eq).map((s) => s.id);
    g.classList.toggle("fuera", ids.some((s) => fuera(s, L[s])));
    g.classList.toggle("senalado", ids.some((s) => senal.has(s)));
  }
  nivel("lvl-betun", L.POR_niv_betum_dep, 45, 150);
  nivel("lvl-sol", L.POR_niv_solucion_dep, 232, 118);
  const pEmu = 100 * (15 - L.DIS_niv_emulsion_dep) / 15;
  nivel("lvl-emu", pEmu, 125, 170);
  $("t-nivel-emu").textContent = `Nivel ${num(pEmu, 0)} %`;
  const prod = d.operacion === "Produccion", limp = d.operacion === "Limpieza";
  $("flujo-betun").classList.toggle("activo", prod);
  $("flujo-sol").classList.toggle("activo", prod);
  $("flujo-agua").classList.toggle("activo", limp);
  // El intercambiador solo se usa al fabricar con asfalto plastomérico; la emulsión convencional va por la línea directa
  const usaInt = prod && d.tipo === "Plastomerico";
  $("flujo-emu-int").classList.toggle("activo", usaInt);
  $("flujo-emu-bypass").classList.toggle("activo", (prod && !usaInt) || limp);
  $("g-E-301").style.opacity = usaInt ? 1 : 0.45;
  $("rotor").classList.toggle("girando", prod || limp);
  $("t-uso-intercambiador").textContent = usaInt ? "en uso (plastomérico)" : "sin uso";
  $("t-producto").textContent = prod ? (d.tipo === "Plastomerico" ? "Fabricando: emulsión con asfalto plastomérico" : "Fabricando: emulsión convencional")
    : limp ? "Limpieza de línea con agua y aire" : `Sin producción (${OPERACION[d.operacion]?.toLowerCase() || "detenida"})`;
}

// ------------------------------------------------------------------ diagnóstico
function posLog(v) { return Math.min(100, Math.max(0, (Math.log10(Math.max(v, 1e-6)) + 2) / 4 * 100)); }

function renderDiagnostico() {
  const ev = S.ultimo.evaluacion, F = S.info.fallas;
  if (ev.identificacion === null) {
    $("id-valor").innerHTML = `<span class="marca-estado"></span>Molino detenido`;
  } else {
    const f = F[ev.identificacion] || { titulo: ev.identificacion, nivel: "alerta" };
    $("id-valor").innerHTML = `<span class="marca-estado ${f.nivel}"></span>${esc(f.titulo)}`;
  }
  const ae = ev.autoencoder;
  if (ae) {
    $("ae-valor").innerHTML = `<span class="marca-estado ${ae.anomalia ? "desconocida" : "normal"}"></span>Error ${num(ae.error, 3)} <small>umbral ${num(S.info.modelos.umbral_ae, 3)}</small>`;
    $("ae-relleno").style.width = `${posLog(ae.error)}%`;
    $("ae-relleno").classList.toggle("alto", ae.anomalia);
    $("ae-aportes").innerHTML = ae.sensores.map((s) => `<li><span>${esc(s.nombre)}</span><span>${Math.round(s.aporte * 100)} %</span></li>`).join("");
  } else {
    $("ae-valor").textContent = "Molino detenido"; $("ae-relleno").style.width = "0"; $("ae-aportes").innerHTML = "";
  }
  const c = $("coherencia");
  c.className = `coherencia ${["Normal", "Detenida"].includes(ev.estado) ? "ok" : "mal"}`;
  c.textContent = ev.origen;
}

// ------------------------------------------------------------------ riesgo (resumen)
function renderRiesgoResumen() {
  const p = S.ultimo.prediccion;
  if (!p) { $("riesgo-resumen").innerHTML = `<li>Modelo predictivo no cargado.</li>`; return; }
  $("pred-hora").textContent = `actualizado ${hora(p.tiempo)} ${fecha(p.tiempo)}`;
  const orden = { "24 h": 0, "5 días": 1, "15 días": 2 };
  const filas = [...p.filas].sort((a, b) => (orden[a.nivel] ?? 9) - (orden[b.nivel] ?? 9));
  $("riesgo-resumen").innerHTML = filas.map((f) => `<li><span>${esc(f.nombre)}</span>${f.nivel
    ? `<span class="chip-riesgo ${CLASE_HZ[f.nivel]}">Riesgo en ${f.nivel}</span>` : `<span class="riesgo-ok">Sin riesgo</span>`}</li>`).join("");
}

// ------------------------------------------------------------------ gráficos
function prepararCanvas(cv) {
  if (!cv.dataset.h) { cv.dataset.h = cv.getAttribute("height"); cv.style.height = `${cv.dataset.h}px`; }
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = parseInt(cv.dataset.h);
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function graficoLinea(cv, puntos, { banda, umbral, log, etiquetasX = true } = {}) {
  const { ctx, w, h } = prepararCanvas(cv);
  const izq = 46, der = 8, arr = 6, abj = etiquetasX ? 18 : 6;
  const vals = puntos.map((p) => p.v).filter((v) => v !== null && !Number.isNaN(v));
  ctx.font = "11px sans-serif";
  if (!vals.length) { ctx.fillStyle = css("--tenue"); ctx.fillText("Sin datos todavía", izq, h / 2); return; }
  const tr = log ? (v) => Math.log10(Math.max(v, 1e-4)) : (v) => v;
  let lo = Math.min(...vals.map(tr)), hi = Math.max(...vals.map(tr));
  if (banda) { lo = Math.min(lo, tr(banda[0])); hi = Math.max(hi, tr(banda[1])); }
  if (umbral) { lo = Math.min(lo, tr(umbral)); hi = Math.max(hi, tr(umbral)); }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const X = (i) => izq + (puntos.length > 1 ? (i / (puntos.length - 1)) * (w - izq - der) : 0);
  const Y = (v) => arr + (1 - (tr(v) - lo) / (hi - lo)) * (h - arr - abj);
  if (banda) { ctx.fillStyle = "rgba(46,125,79,0.13)"; ctx.fillRect(izq, Y(banda[1]), w - izq - der, Y(banda[0]) - Y(banda[1])); }
  ctx.strokeStyle = css("--linea"); ctx.fillStyle = css("--tenue");
  [lo + pad, (lo + hi) / 2, hi - pad].forEach((t) => {
    const y = arr + (1 - (t - lo) / (hi - lo)) * (h - arr - abj);
    ctx.beginPath(); ctx.moveTo(izq, y); ctx.lineTo(w - der, y); ctx.stroke(); ctx.fillText(num(log ? 10 ** t : t), 0, y + 4);
  });
  if (umbral) { ctx.setLineDash([5, 4]); ctx.strokeStyle = css("--tinta"); ctx.beginPath(); ctx.moveTo(izq, Y(umbral)); ctx.lineTo(w - der, Y(umbral)); ctx.stroke(); ctx.setLineDash([]); }
  ctx.fillStyle = "rgba(198,45,31,0.10)";
  puntos.forEach((p, i) => { if (p.anomalo) ctx.fillRect(X(i) - 1, arr, Math.max(2, (w - izq - der) / puntos.length), h - arr - abj); });
  ctx.strokeStyle = css("--tinta"); ctx.lineWidth = 1.5; ctx.beginPath();
  puntos.forEach((p, i) => (i ? ctx.lineTo(X(i), Y(p.v)) : ctx.moveTo(X(i), Y(p.v)))); ctx.stroke(); ctx.lineWidth = 1;
  if (puntos.length < 40) { ctx.fillStyle = css("--tinta"); puntos.forEach((p, i) => { ctx.beginPath(); ctx.arc(X(i), Y(p.v), 3, 0, 7); ctx.fill(); }); }
  if (etiquetasX && puntos[0]?.t) {
    ctx.fillStyle = css("--tenue");
    ctx.fillText(`${fecha(puntos[0].t).slice(0, 5)} ${hora(puntos[0].t)}`, izq, h - 3);
    const u = `${fecha(puntos.at(-1).t).slice(0, 5)} ${hora(puntos.at(-1).t)}`;
    ctx.fillText(u, w - der - ctx.measureText(u).width, h - 3);
  }
}

function serieDe(id, n) {
  if (!S.buf) return [];
  const L = S.buf.tiempo.length, i0 = Math.max(0, L - n), out = [];
  for (let i = i0; i < L; i++) out.push({ t: S.buf.tiempo[i], v: S.buf[id][i], anomalo: !["Normal", "Detenida"].includes(S.buf.estado[i]) });
  return out;
}

const MINIS = ["AMP_vfd_motor_molino", "VIB_vel_motor_molino", "PRE_dif_filtro_bar"];
function construirMinis() {
  $("minis").innerHTML = MINIS.map((id) => { const s = sensor(id);
    return `<div class="tarjeta mini"><div class="tarjeta-cab"><h2>${s.nombre}</h2><strong id="mini-v-${id}" class="mini-valor">--</strong></div>
      <canvas id="mini-${id}" height="120" aria-label="Tendencia ${s.nombre}"></canvas></div>`; }).join("");
}
function renderMinis() {
  MINIS.forEach((id) => {
    const v = S.ultimo.lecturas[id], el = $(`mini-v-${id}`);
    el.innerHTML = `${num(v)} <small>${sensor(id).unidad}</small>`; el.classList.toggle("fuera", fuera(id, v));
    graficoLinea($(`mini-${id}`), serieDe(id, 720), { banda: S.ultimo.banda[id], etiquetasX: false });
  });
}

function renderKpis() {
  const k = S.ultimo.kpis, [lo, hi] = k.relacion_objetivo;
  const rel = $("kpi-relacion");
  rel.querySelector("strong").innerHTML = k.relacion_betun === null ? "--" : `${num(k.relacion_betun, 1)} <small>%</small>`;
  rel.querySelector("em").textContent = k.relacion_betun === null ? "Solo durante la producción" : `Objetivo ${lo}–${hi} %`;
  rel.classList.toggle("fuera", k.relacion_betun !== null && (k.relacion_betun < lo || k.relacion_betun > hi));
  $("kpi-produccion").querySelector("strong").innerHTML = `${num(k.produccion_t, 1)} <small>t</small>`;
  $("kpi-normal").querySelector("strong").innerHTML = k.operacion_normal_pct === null ? "--" : `${num(k.operacion_normal_pct, 1)} <small>%</small>`;
  $("kpi-energia").querySelector("strong").innerHTML = `${num(k.energia_kwh, 0)} <small>kWh</small>`;
  $("kpi-minutos").textContent = `${num(k.horas_marcha, 1)} h de molino en marcha`;
}

// ------------------------------------------------------------------ predicción
function renderPrediccion() {
  const p = S.ultimo.prediccion;
  if (!p) { $("tabla-semaforo").innerHTML = "<tr><td>Modelo predictivo no cargado.</td></tr>"; return; }
  $("pred-hora-2").textContent = `Predicción emitida a las ${hora(p.tiempo)} del ${fecha(p.tiempo)}`;
  if (!$("horizonte-graf").options.length) {
    $("horizonte-graf").innerHTML = p.horizontes.map((h) => `<option>${h}</option>`).join("");
    $("horizonte-graf").value = "5 días"; $("horizonte-graf").onchange = renderGrafRiesgo;
  }
  const celda = (f, hz) => {
    const c = f.horizontes[hz], cls = c.alerta ? CLASE_HZ[hz] : "riesgo-ok";
    const det = f.metodo === "Tendencia"
      ? (f.dias === null ? "sin tendencia" : f.dias === 0 ? "en el límite" : `≈ ${num(f.dias, 1)} días`)
      : `${Math.round(100 * c.prob)} % (umbral ${Math.round(100 * c.umbral)} %)`;
    return `<td class="celda ${cls}">${c.alerta ? "ALTO" : "bajo"}<small>${det}</small></td>`;
  };
  $("tabla-semaforo").innerHTML = `<thead><tr><th>Falla</th><th>Método</th>${p.horizontes.map((h) => `<th style="text-align:center">${h}</th>`).join("")}
    <th>Desde la última intervención</th><th>Acción sugerida</th><th></th></tr></thead><tbody>` +
    p.filas.map((f) => `<tr><td><strong>${esc(f.nombre)}</strong></td><td>${f.metodo}</td>${p.horizontes.map((h) => celda(f, h)).join("")}
      <td>${num(f.horas_desde_intervencion / 24, 1)} días</td><td>${f.nivel ? esc(f.accion) : ""}</td>
      <td><button class="btn btn-chico ${f.nivel ? "btn-primario" : ""}" data-intervenir="${f.equipo}" data-desc="${esc(f.accion)}">Registrar intervención</button></td></tr>`).join("") + "</tbody>";
  renderGrafRiesgo();
}

function renderGrafRiesgo() {
  const hz = $("horizonte-graf").value || "5 días", cv = $("graf-riesgo");
  const { ctx, w, h } = prepararCanvas(cv);
  const izq = 40, der = 8, arr = 8, abj = 20, H = S.predHist;
  ctx.font = "11px sans-serif";
  if (H.length < 2) { ctx.fillStyle = css("--tenue"); ctx.fillText("Se necesitan al menos dos horas simuladas.", izq, h / 2); return; }
  const X = (i) => izq + (i / (H.length - 1)) * (w - izq - der), Y = (v) => arr + (1 - v) * (h - arr - abj);
  ctx.strokeStyle = css("--linea"); ctx.fillStyle = css("--tenue");
  [0, 0.5, 1].forEach((v) => { ctx.beginPath(); ctx.moveTo(izq, Y(v)); ctx.lineTo(w - der, Y(v)); ctx.stroke(); ctx.fillText(`${v * 100} %`, 0, Y(v) + 4); });
  const ml = H.at(-1).filas.filter((f) => f.metodo !== "Tendencia");
  for (const f of ml) {
    const col = COLOR_FALLA[f.falla] || "#333";
    ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.beginPath();
    H.forEach((p, i) => { const v = p.filas.find((x) => x.falla === f.falla).horizontes[hz].prob; i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)); });
    ctx.stroke(); ctx.setLineDash([5, 4]); ctx.lineWidth = 1;
    const u = f.horizontes[hz].umbral; ctx.beginPath(); ctx.moveTo(izq, Y(u)); ctx.lineTo(w - der, Y(u)); ctx.stroke(); ctx.setLineDash([]);
  }
  ctx.fillStyle = css("--tenue");
  ctx.fillText(`${fecha(H[0].tiempo).slice(0, 5)} ${hora(H[0].tiempo)}`, izq, h - 4);
  const u = `${fecha(H.at(-1).tiempo).slice(0, 5)} ${hora(H.at(-1).tiempo)}`; ctx.fillText(u, w - der - ctx.measureText(u).width, h - 4);
  $("leyenda-riesgo").innerHTML = ml.map((f) => `<span><b style="color:${COLOR_FALLA[f.falla]}">■</b> ${esc(f.nombre)}</span>`).join("");
}

// ------------------------------------------------------------------ tendencias
function renderTendencias() {
  const id = $("sensor-tendencia").value;
  graficoLinea($("tendencia-grande"), serieDe(id, S.MAX), { banda: S.ultimo?.banda?.[id] });
  if (!S.ultimo) return;
  $("tabla-lecturas").innerHTML = `<thead><tr><th>Equipo</th><th>Sensor</th><th class="num">Valor</th><th class="num">Banda normal (modo actual)</th></tr></thead><tbody>` +
    S.info.sensores.map((s) => { const v = S.ultimo.lecturas[s.id], b = S.ultimo.banda[s.id];
      return `<tr class="${fuera(s.id, v) ? "fuera" : ""}"><td>${s.equipo}</td><td>${esc(s.nombre)}</td><td class="num">${valorTexto(s.id, v)}</td>
        <td class="num">${b ? `${num(b[0])} a ${num(b[1])}` : ""}</td></tr>`; }).join("") + "</tbody>";
}

// ------------------------------------------------------------------ alarmas
function tarjetaAlarma(a, ahora) {
  const min = minutosEntre(a.inicio, a.fin || ahora);
  const rec = a.reconocida_en ? `reconocida por ${esc(a.reconocida_por)}` : "sin reconocer";
  let retro = "";
  if (a.tipo === "modelo") {
    retro = a.feedback
      ? `<span class="respondida">Respuesta registrada: ${{ correcto: "diagnóstico correcto", incorrecto: "diagnóstico incorrecto", otra: "era otra falla" }[a.feedback]}</span>`
      : `<span>¿El diagnóstico fue correcto?</span><button class="btn btn-chico" data-retro="correcto" data-id="${a.id}">Sí</button>
         <button class="btn btn-chico" data-retro="incorrecto" data-id="${a.id}">No</button><button class="btn btn-chico" data-retro="otra" data-id="${a.id}">Era otra falla</button>`;
  }
  return `<div class="alarma"><div class="alarma-cab"><strong>${esc(a.titulo)}</strong><span class="prioridad ${a.prioridad}">${a.prioridad === "alta" ? "Alta" : "Media"}</span></div>
    <p>Desde ${hora(a.inicio)} del ${fecha(a.inicio)}, ${min} min, ${rec}. ${a.tipo === "limite" ? "Regla fija." : esc(a.origen)}</p>
    <div class="acciones">${a.reconocida_en ? "" : `<button class="btn btn-chico btn-oscuro" data-reconocer="${a.id}">Reconocer</button>`}${retro}</div>
    <div class="otra" id="otra-${a.id}" hidden><input type="text" maxlength="300" placeholder="¿Qué falla era?" aria-label="Describe la falla real">
      <button class="btn btn-chico btn-primario" data-enviar-otra="${a.id}">Enviar</button></div></div>`;
}
function renderListaAlarmas(cont, lista) {
  if (cont.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  cont.innerHTML = lista.length ? lista.map((a) => tarjetaAlarma(a, S.ultimo?.tiempo)).join("") : `<p class="vacio">No hay alarmas activas.</p>`;
}
function renderAlarmasActivas() {
  renderListaAlarmas($("alarmas-activas"), S.ultimo.alarmas);
  if (S.vista === "alarmas") renderListaAlarmas($("alarmas-activas-2"), S.ultimo.alarmas);
}
async function reconocer(id) {
  await api(`/api/alarmas/${id}/reconocer`, { method: "POST", body: { usuario: operador() } });
  const a = S.ultimo.alarmas.find((x) => String(x.id) === String(id)); if (a) { a.reconocida_en = "ahora"; a.reconocida_por = operador(); }
  render();
}
async function retro(id, valor, texto) {
  await api(`/api/alarmas/${id}/retroalimentacion`, { method: "POST", body: { valor, texto } });
  const a = S.ultimo.alarmas.find((x) => String(x.id) === String(id)); if (a) a.feedback = valor;
  document.activeElement?.blur(); render(); if (S.vista === "alarmas") cargarAlarmas();
}
async function cargarAlarmas() {
  const d = await api("/api/alarmas");
  renderListaAlarmas($("alarmas-activas-2"), d.activas);
  const fb = { correcto: "Correcto", incorrecto: "Incorrecto", otra: "Otra falla" };
  $("tabla-alarmas").innerHTML = `<thead><tr><th>Inicio</th><th>Fin</th><th>Alarma</th><th>Prioridad</th><th>Origen</th><th>Reconocida por</th><th>Diagnóstico</th></tr></thead><tbody>` +
    (d.historial.map((a) => `<tr><td>${fecha(a.inicio)} ${hora(a.inicio)}</td><td>${a.fin ? hora(a.fin) : "activa"}</td><td>${esc(a.titulo)}</td>
      <td>${a.prioridad}</td><td>${a.tipo === "limite" ? "Regla fija" : "Modelo"}</td><td>${esc(a.reconocida_por || "")}</td>
      <td>${a.feedback ? fb[a.feedback] + (a.feedback_texto ? `: ${esc(a.feedback_texto)}` : "") : ""}</td></tr>`).join("") ||
      `<tr><td colspan="7" class="vacio">Sin alarmas registradas.</td></tr>`) + "</tbody>";
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.reconocer) await reconocer(b.dataset.reconocer);
  else if (b.dataset.retro === "otra") { $(`otra-${b.dataset.id}`).hidden = false; $(`otra-${b.dataset.id}`).querySelector("input").focus(); }
  else if (b.dataset.retro) await retro(b.dataset.id, b.dataset.retro, "");
  else if (b.dataset.enviarOtra) await retro(b.dataset.enviarOtra, "otra", $(`otra-${b.dataset.enviarOtra}`).querySelector("input").value.trim());
  else if (b.dataset.intervenir) await intervenir(b.dataset.intervenir, "Preventiva", b.dataset.desc);
});

// ------------------------------------------------------------------ salud
async function cargarSalud() {
  const s = await api("/api/salud");
  graficoLinea($("salud-grande"), s.dias.map((x) => ({ t: `${x.dia}T00:00`, v: x.error_medio })), { umbral: s.umbral, log: true });
  $("tabla-salud").innerHTML = `<thead><tr><th>Día</th><th class="num">Error medio</th><th class="num">Minutos en marcha</th><th class="num">Minutos con falla o anomalía</th></tr></thead><tbody>` +
    (s.dias.slice().reverse().map((x) => `<tr><td>${fecha(x.dia + "T")}</td><td class="num">${num(x.error_medio, 3)}</td><td class="num">${num(x.minutos, 0)}</td>
      <td class="num">${num(x.minutos_anomalos, 0)}</td></tr>`).join("") || `<tr><td colspan="4" class="vacio">Sin datos.</td></tr>`) + "</tbody>";
}

// ------------------------------------------------------------------ mantenimiento
function prepararMantenimiento() {
  $("m-equipo").innerHTML = Object.entries(S.info.equipos).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("form-mant").onsubmit = async (e) => { e.preventDefault(); await intervenir($("m-equipo").value, $("m-tipo").value, $("m-desc").value.trim()); $("m-desc").value = ""; };
}
async function intervenir(equipo, tipo, descripcion) {
  try {
    const r = await api("/api/mantenimiento", { method: "POST", body: { equipo, tipo, descripcion, usuario: operador() } });
    const msg = `${tipo} registrada en ${S.info.equipos[equipo]} (${fecha(r.tiempo)} ${hora(r.tiempo)}).` +
      (r.escenario_resuelto ? ` La falla simulada "${r.escenario_resuelto}" quedó corregida.` : "");
    $("m-mensaje").textContent = msg; $("m-mensaje").className = "mensaje ok";
    if (S.vista !== "mantenimiento") alert(msg);
    cargarMantenimiento(); if (!S.reproduciendo) tick();
  } catch (e) { $("m-mensaje").textContent = e.message; $("m-mensaje").className = "mensaje error"; }
}
async function cargarMantenimiento() {
  const m = await api("/api/mantenimiento");
  $("mant-tiempo").textContent = `al ${fecha(m.tiempo)} ${hora(m.tiempo)}`;
  $("kpi-planificado").querySelector("strong").innerHTML = m.pct_planificado === null ? "--" : `${num(m.pct_planificado, 1)} <small>%</small>`;
  $("kpi-intervenciones").querySelector("strong").textContent = m.total;
  $("tabla-equipos").innerHTML = `<thead><tr><th>Equipo</th><th class="num">Correctivas</th><th class="num">Preventivas</th><th class="num">MTBF</th><th>Última intervención</th><th class="num">Hace</th></tr></thead><tbody>` +
    m.equipos.map((e) => `<tr><td>${esc(e.equipo)}</td><td class="num">${e.correctivas}</td><td class="num">${e.preventivas}</td>
      <td class="num">${e.mtbf_dias === null ? "--" : `${num(e.mtbf_dias, 1)} días`}</td><td>${e.ultima_intervencion ? `${fecha(e.ultima_intervencion)} ${hora(e.ultima_intervencion)}` : "--"}</td>
      <td class="num">${e.horas_desde === null ? "--" : `${num(e.horas_desde / 24, 1)} días`}</td></tr>`).join("") + "</tbody>";
  $("tabla-bitacora").innerHTML = `<thead><tr><th>Fecha</th><th>Equipo</th><th>Tipo</th><th>Descripción</th></tr></thead><tbody>` +
    m.bitacora.map((b) => `<tr><td>${fecha(b.tiempo)} ${hora(b.tiempo)}</td><td>${esc(b.equipo)}</td><td>${esc(b.tipo)}</td><td>${esc(b.descripcion)}</td></tr>`).join("") + "</tbody>";
}

// ------------------------------------------------------------------ registro
async function cargarEtiquetas() {
  const filas = await api("/api/etiquetas"), fb = { correcto: "Correcto", incorrecto: "Incorrecto", otra: "Otra falla" };
  $("tabla-etiquetas").innerHTML = `<thead><tr><th>#</th><th>Inicio</th><th>Alarma</th><th>Respuesta</th><th>Comentario</th><th>Reconocida por</th></tr></thead><tbody>` +
    (filas.map((f) => `<tr><td>${f.id}</td><td>${fecha(f.inicio)} ${hora(f.inicio)}</td><td>${esc(f.titulo)}</td><td>${fb[f.feedback]}</td>
      <td>${esc(f.feedback_texto || "")}</td><td>${esc(f.reconocida_por || "")}</td></tr>`).join("") ||
      `<tr><td colspan="6" class="vacio">Todavía no hay respuestas.</td></tr>`) + "</tbody>";
}

// ------------------------------------------------------------------ navegación y controles
function prepararTabs() {
  document.querySelectorAll(".nav button").forEach((b) => { b.onclick = () => mostrarVista(b.dataset.vista); });
  $("an-detalle").onclick = () => mostrarVista("alarmas");
  $("ver-prediccion").onclick = () => mostrarVista("prediccion");
}
function mostrarVista(v) {
  S.vista = v;
  document.querySelectorAll(".nav button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.vista === v)));
  document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== v; });
  if (!S.ultimo) return;
  ({ prediccion: renderPrediccion, tendencias: renderTendencias, alarmas: cargarAlarmas, salud: cargarSalud,
     mantenimiento: cargarMantenimiento, registro: cargarEtiquetas, proceso: render })[v]?.();
}

function prepararControles() {
  $("play").onclick = () => { S.reproduciendo = !S.reproduciendo; $("play").textContent = S.reproduciendo ? "Pausar" : "Reanudar"; };
  const meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  $("ir-a").innerHTML = `<option value="">Elegir…</option><optgroup label="Inicio de cada mes">` +
    meses.map((m, i) => `<option value="fecha:2026-${String(i + 1).padStart(2, "0")}-01T07:00">1 de ${m}</option>`).join("") +
    `</optgroup><optgroup label="3 días antes de una falla real">` +
    S.info.episodios.map((e) => `<option value="idx:${Math.max(0, e.indice - 3 * 1440)}">${e.inicio}: ${esc(S.info.corto[e.estado] || e.estado)}</option>`).join("") + "</optgroup>";
  $("ir-a").onchange = async () => {
    const v = $("ir-a").value; if (!v) return;
    const body = v.startsWith("fecha:") ? { fecha: v.slice(6) } : { indice: parseInt(v.slice(4)) };
    S.ocupado = true;
    try { await api("/api/ir", { method: "POST", body }); reiniciarBuffers(); $("escenario-rapido").value = ""; $("funcionamiento").value = ""; } finally { S.ocupado = false; }
    $("ir-a").value = ""; tick();
  };
  $("escenario-rapido").onchange = () => activarEscenario($("escenario-rapido").value || null);
  $("funcionamiento").onchange = async () => {
    S.ocupado = true;
    try { await api("/api/funcionamiento", { method: "POST", body: { modo: $("funcionamiento").value || null } }); reiniciarBuffers(); }
    finally { S.ocupado = false; }
    tick();
  };
  window.addEventListener("resize", () => { if (S.ultimo) render(); });
}

// ------------------------------------------------------------------ escenarios
async function cargarEscenarios() {
  S.escenarios = await api("/api/escenarios");
  const grupos = { conocida: "Fallas conocidas, con degradación progresiva", nueva: "Fallas que ningún modelo vio", personalizada: "Mis fallas" };
  $("escenarios").innerHTML = `<div class="escenarios-grupo"><div class="botones"><button class="btn btn-oscuro" data-escenario="">Quitar falla inyectada</button></div></div>` +
    Object.entries(grupos).map(([cat, t]) => { const l = S.escenarios.filter((e) => e.categoria === cat); if (!l.length) return "";
      return `<div class="escenarios-grupo"><h3>${t}</h3><div class="botones">${l.map((e) =>
        `<button class="btn" data-escenario="${esc(e.nombre)}" title="${esc(e.descripcion)}">${esc(e.nombre)}</button>`).join("")}</div></div>`; }).join("");
  $("escenarios").querySelectorAll("button").forEach((b) => { b.onclick = () => activarEscenario(b.dataset.escenario || null); });
  $("escenario-rapido").innerHTML = `<option value="">Ninguna (datos reales)</option>` + S.escenarios.map((e) => `<option value="${esc(e.nombre)}">${esc(e.nombre)}</option>`).join("");
  renderListaMias();
}
async function activarEscenario(nombre, escenario = null) {
  await api("/api/escenario", { method: "POST", body: escenario ? { escenario } : { nombre } });
  $("escenario-rapido").value = escenario ? "" : nombre || "";
  $("escenarios").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.escenario || null) === nombre && !escenario)));
  if (!S.reproduciendo) tick();
}

// ------------------------------------------------------------------ editor de fallas
function prepararEditor() {
  $("f-agregar").onclick = () => filaEfecto();
  $("f-probar").onclick = () => { const e = leerFormulario(); if (e) { activarEscenario(null, e); mensaje(`Probando "${e.nombre}".`, "ok"); } };
  $("f-limpiar").onclick = limpiarEditor;
  $("form-falla").onsubmit = guardarFalla;
  limpiarEditor();
}
function filaEfecto(ef = { sensor: "AMP_vfd_motor_molino", operacion: "sumar", valor: "" }) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><select aria-label="Sensor">${S.info.sensores.map((s) => `<option value="${s.id}" ${s.id === ef.sensor ? "selected" : ""}>${esc(s.nombre)} (${s.unidad || s.equipo})</option>`).join("")}</select></td>
    <td><select aria-label="Tipo de cambio"><option value="sumar" ${ef.operacion === "sumar" ? "selected" : ""}>Sumar</option>
      <option value="multiplicar" ${ef.operacion === "multiplicar" ? "selected" : ""}>Multiplicar por</option>
      <option value="fijar" ${ef.operacion === "fijar" ? "selected" : ""}>Fijar en</option></select></td>
    <td><input type="number" step="any" aria-label="Valor" value="${ef.valor}"></td><td><button type="button" class="btn btn-chico btn-peligro">Quitar</button></td>`;
  tr.querySelector("button").onclick = () => tr.remove();
  $("f-efectos").appendChild(tr);
}
function leerFormulario() {
  const nombre = $("f-nombre").value.trim();
  const efectos = [...$("f-efectos").querySelectorAll("tr")].map((tr) => { const [s, op] = tr.querySelectorAll("select");
    return { sensor: s.value, operacion: op.value, valor: parseFloat(tr.querySelector("input").value) }; });
  if (!nombre) { mensaje("Ponle un nombre a la falla.", "error"); return null; }
  if (!efectos.length || efectos.some((e) => Number.isNaN(e.valor))) { mensaje("Completa al menos un sensor con su valor.", "error"); return null; }
  return { nombre, efectos, descripcion: $("f-descripcion").value.trim(), evolucion: document.querySelector("input[name=f-evol]:checked").value,
           minutos: Math.max(1, Math.min(20160, parseInt($("f-minutos").value) || 1440)) };
}
async function guardarFalla(ev) {
  ev.preventDefault(); const e = leerFormulario(); if (!e) return;
  try { await api("/api/escenarios", { method: "POST", body: e }); await cargarEscenarios(); mensaje(`Falla "${e.nombre}" guardada.`, "ok"); }
  catch (err) { mensaje(err.message, "error"); }
}
function renderListaMias() {
  const mias = S.escenarios.filter((e) => e.categoria === "personalizada");
  $("lista-mias-vacia").hidden = mias.length > 0; $("lista-mias").innerHTML = "";
  mias.forEach((e) => {
    const li = document.createElement("li"); li.innerHTML = `<strong></strong><p></p>`;
    li.querySelector("strong").textContent = e.nombre;
    li.querySelector("p").textContent = `${e.efectos.length} sensor(es), ${e.evolucion === "gradual" ? `gradual en ${e.minutos} min` : "de golpe"}`;
    const mk = (t, cls, fn) => { const b = document.createElement("button"); b.className = `btn btn-chico ${cls}`; b.textContent = t; b.onclick = fn; return b; };
    li.append(mk("Simular", "", () => activarEscenario(e.nombre)), " ", mk("Eliminar", "btn-peligro", async () => {
      if (!confirm(`¿Eliminar "${e.nombre}"?`)) return; await api(`/api/escenarios/${encodeURIComponent(e.nombre)}`, { method: "DELETE" }); cargarEscenarios(); }));
    $("lista-mias").appendChild(li);
  });
}
function limpiarEditor() { $("form-falla").reset(); $("f-efectos").innerHTML = ""; filaEfecto(); mensaje("", ""); }
function mensaje(t, tipo) { const m = $("f-mensaje"); m.textContent = t; m.className = `mensaje ${tipo}`; }

iniciar().catch((e) => { $("an-titulo").textContent = "No se pudo iniciar el dashboard"; $("an-accion").textContent = `${e.message}. Revisa que el servidor esté corriendo.`; });
