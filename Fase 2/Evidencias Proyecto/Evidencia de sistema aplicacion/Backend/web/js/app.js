/* Dashboard del molino coloidal MC-01 (Química Latinoamericana).
   Cada pestaña lee su endpoint en /api; se actualiza cada 5 s y de inmediato cuando el
   servidor avisa por WebSocket que llegó un resultado nuevo de los modelos. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ sesión
  const usuario = Sesion.usuario;
  if (!Sesion.token || !usuario) { location.replace("/login.html"); return; }
  if (usuario.debe_cambiar_clave) { Sesion.cerrar(); location.replace("/login.html"); return; }
  const esAdmin = usuario.rol === "administrador";

  // ------------------------------------------------------------------ catálogos
  const FALLAS = [
    ["Filtro_Obstruido", "Filtro"],
    ["Sobrecarga_Motor_Por_Asfalto_Frio", "Sobrecarga"],
    ["Advertencia_Radar_Sucio_Betun", "Radar sucio"],
    ["Cortocircuito_Transmisor_Caudal_Sol", "Cortocircuito"],
    ["Falla_Electrica_PT100_Betun", "Pt100"],
    ["Ensuciamiento_Intercambiador", "Intercambiador"],
    ["Desgaste_Rodamientos_Molino", "Rodamientos"],
  ];
  const CORTO = Object.fromEntries(FALLAS);
  const HORIZONTES = [["24h", "24 h"], ["5d", "5 días"], ["15d", "15 días"]];
  const TEXTO_HZ = Object.fromEntries(HORIZONTES);

  const MED_IZQ = [["AMP_vfd_motor_molino", "Corriente motor"], ["TOR_vfd_motor_molino", "Torque"],
    ["VIB_vel_motor_molino", "Vibración"], ["RPM_motor_molino", "Velocidad"],
    ["TEM_emulsion_molino_out", "T° salida molino"], ["CAU_bomba_lpm", "Caudal bomba"]];
  const MED_DER = [["TEM_son_betum_in", "Temperatura betún"], ["TEM_son_solucion_in", "Temp. solución"],
    ["PRE_dif_filtro_bar", "ΔP filtro"], ["PRE_intercambiador_bar", "Presión interc."],
    ["AMP_eco_betum_dep", "Eco radar betún"], ["AE", "Índice de salud (AE)"]];
  const DECIMALES = { RPM_motor_molino: 0, TOR_vfd_motor_molino: 0, CAU_bomba_lpm: 0, PRE_dif_filtro_bar: 2,
    POR_niv_betum_dep: 0, POR_niv_solucion_dep: 0 };
  const RANGO_DEFECTO = { AMP_eco_betum_dep: [0, 100] };
  const SOLO_MARCHA = new Set(["AMP_vfd_motor_molino", "TOR_vfd_motor_molino", "VIB_vel_motor_molino",
    "RPM_motor_molino", "CAU_bomba_lpm", "PRE_dif_filtro_bar", "TEM_emulsion_molino_out"]);

  // Sensores que se grafican en Proceso según la falla activa
  const TENDENCIA_FALLA = {
    Filtro_Obstruido: ["PRE_dif_filtro_bar", "CAU_bomba_lpm", "AMP_vfd_motor_molino"],
    Sobrecarga_Motor_Por_Asfalto_Frio: ["TEM_son_betum_in", "AMP_vfd_motor_molino", "TOR_vfd_motor_molino"],
    Advertencia_Radar_Sucio_Betun: ["AMP_eco_betum_dep", "TEM_son_betum_in", "AMP_vfd_motor_molino"],
    Cortocircuito_Transmisor_Caudal_Sol: ["AMP_cau_solucion_in", "FRE_cau_solucion_in", "CAU_bomba_lpm"],
    Falla_Electrica_PT100_Betun: ["VOLT_son_betum_in", "TEM_son_betum_in", "RES_son_betum_in"],
    Ensuciamiento_Intercambiador: ["PRE_intercambiador_bar", "TEM_son_emulsion_out", "TEM_emulsion_molino_out"],
    Desgaste_Rodamientos_Molino: ["VIB_vel_motor_molino", "AMP_vfd_motor_molino", "RPM_motor_molino"],
  };
  const TENDENCIA_DEFECTO = ["PRE_dif_filtro_bar", "CAU_bomba_lpm", "AMP_vfd_motor_molino"];
  const ESTADO_TEXTO = { produccion: "En producción", limpieza: "Limpieza de línea", detenida: "Planta detenida",
    preparacion: "En preparación", espera: "En espera", mantenimiento: "En mantenimiento", falla: "En falla" };
  const ESTADO_PUNTO = { produccion: "verde", limpieza: "ambar", detenida: "gris", preparacion: "ambar",
    espera: "gris", mantenimiento: "naranja", falla: "rojo" };
  const TIPO_TEXTO = { convencional: "convencional", plastomerico: "plastomérico", ninguno: "" };

  const COLOR = { verde: "#45c46a", rojo: "#f0524f", morado: "#a77bf3", gris: "#6b7480", naranja: "#f28c38",
    azul: "#4ea1ff", texto: "#eceef1", texto2: "#a3abb6", borde: "#2a313c" };

  // ------------------------------------------------------------------ utilidades
  const $ = (id) => document.getElementById(id);
  const ZONA_PLANTA = "America/Santiago";
  const partes = (iso, op) => {
    const p = {};
    new Intl.DateTimeFormat("es-CL", { timeZone: ZONA_PLANTA, hour12: false, ...op }).formatToParts(new Date(iso))
      .forEach((x) => { p[x.type] = x.value; });
    return p;
  };
  function fFecha(iso) { if (!iso) return "—"; const p = partes(iso, { day: "2-digit", month: "2-digit", year: "numeric" }); return `${p.day}-${p.month}-${p.year}`; }
  function fHora(iso) { if (!iso) return "—"; const p = partes(iso, { hour: "2-digit", minute: "2-digit" }); return `${p.hour}:${p.minute}`; }
  function fFechaHora(iso) { return iso ? `${fFecha(iso)} ${fHora(iso)}` : "—"; }
  function fDia(dia) { if (!dia) return "—"; const [a, m, d] = String(dia).slice(0, 10).split("-"); return `${d}-${m}-${a}`; }
  function n(v, dec = 1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    return Number(v).toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function pct(v, dec = 0) { return v === null || v === undefined ? "—" : `${n(v * 100, dec)} %`; }
  function minutosEntre(a, b) { return Math.max(0, Math.round((new Date(b) - new Date(a)) / 60000)); }
  function duracion(min) {
    if (min === null || min === undefined) return "—";
    if (min < 60) return `${min} min`;
    if (min < 1440) return `${n(min / 60, 1)} h`;
    return `${n(min / 1440, 1)} días`;
  }
  function vaciar(nodo, ...hijos) { nodo.replaceChildren(...hijos.flat().filter(Boolean)); }
  function filaVacia(tbody, cols, texto) { vaciar(tbody, el("tr", {}, el("td", { colspan: cols, clase: "vacio" }, texto))); }
  function avisar(texto) { const a = $("aviso-global"); a.textContent = texto || ""; a.hidden = !texto; }

  // ------------------------------------------------------------------ gráficos (ECharts)
  const graficos = {};
  function grafico(nodo) {
    if (!window.echarts) return null;
    const id = nodo.id || (nodo.id = "g" + Math.random().toString(36).slice(2));
    if (!graficos[id]) graficos[id] = echarts.init(nodo, null, { renderer: "canvas" });
    return graficos[id];
  }
  window.addEventListener("resize", () => Object.values(graficos).forEach((g) => g.resize()));
  const EJE = { axisLine: { lineStyle: { color: COLOR.borde } }, axisLabel: { color: COLOR.texto2 },
    splitLine: { lineStyle: { color: "#232a34" } } };

  // ------------------------------------------------------------------ cabecera y usuario
  $("usuario-nombre").textContent = usuario.nombre || usuario.email;
  $("usuario-rol").textContent = esAdmin ? "Administrador" : "Operador";
  $("btn-usuario").addEventListener("click", () => {
    const m = $("menu-usuario"); m.hidden = !m.hidden; $("btn-usuario").setAttribute("aria-expanded", String(!m.hidden));
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".usuario")) $("menu-usuario").hidden = true; });
  $("btn-salir").addEventListener("click", () => { Sesion.cerrar(); location.replace("/login.html?motivo=salida"); });
  if (esAdmin) $("tab-usuarios").hidden = false;

  function pintarCabecera(est) {
    if (!est || !est.ts) return;
    $("reloj-hora").textContent = fHora(est.ts);
    $("reloj-fecha").textContent = fFecha(est.ts);
    const tipo = TIPO_TEXTO[est.tipo_asfalto] || "";
    const chip = $("chip-estado");
    chip.querySelector(".punto").className = "punto " + (ESTADO_PUNTO[est.estado] || "gris");
    chip.querySelector(".txt").textContent = (ESTADO_TEXTO[est.estado] || est.estado) +
      (tipo && (est.estado === "produccion" || est.estado === "limpieza") ? `, ${tipo}` : "");
  }

  // ------------------------------------------------------------------ pestañas
  let pestana = "proceso";
  try { const g = sessionStorage.getItem("qla_pestana"); if (g && (g !== "usuarios" || esAdmin)) pestana = g; } catch {}
  function mostrar(tab) {
    pestana = tab;
    try { sessionStorage.setItem("qla_pestana", tab); } catch {}
    document.querySelectorAll(".pestanas [data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".vista").forEach((v) => { v.hidden = v.id !== "vista-" + tab; });
    refrescar(true);
    setTimeout(() => Object.values(graficos).forEach((g) => g.resize()), 30);
  }
  document.querySelectorAll(".pestanas [data-tab]").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.tab)));
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-ir]"); if (b) mostrar(b.dataset.ir); });
  $("banner-ver").addEventListener("click", () => mostrar("alarmas"));

  // ------------------------------------------------------------------ medidores (SVG)
  const SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function arco(cx, cy, r, a0, a1) {
    const p = (a) => [cx + r * Math.cos((a * Math.PI) / 180), cy - r * Math.sin((a * Math.PI) / 180)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${a0 - a1 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }
  const A0 = 200, A1 = -20;
  const medidores = {};
  function crearMedidores(cont, lista) {
    lista.forEach(([tag, nombre]) => {
      const fondo = svg("path", { d: arco(60, 56, 42, A0, A1), class: "arco-fondo" });
      const val = svg("path", { d: arco(60, 56, 42, A0, A1), class: "arco" });
      const txt = svg("text", { x: 60, y: 62, "text-anchor": "middle", class: "valor" });
      const uni = svg("text", { x: 60, y: 82, "text-anchor": "middle", class: "unidad" });
      const s = svg("svg", { viewBox: "0 0 120 88", role: "img", "aria-label": nombre });
      s.append(fondo, val, txt, uni);
      const caja = el("div", { clase: "medidor" }, el("div", { clase: "nombre" }, nombre), s);
      cont.append(caja);
      const largo = val.getTotalLength ? 0 : 0;
      medidores[tag] = { caja, val, txt, uni, largo };
    });
  }
  crearMedidores($("medidores-izq"), MED_IZQ);
  crearMedidores($("medidores-der"), MED_DER);
  function pintarMedidor(tag, valor, frac, color, unidad, dec, clase) {
    const m = medidores[tag]; if (!m) return;
    if (!m.largo) { try { m.largo = m.val.getTotalLength(); } catch { m.largo = 207; } m.val.style.strokeDasharray = m.largo; }
    const f = Math.max(0, Math.min(1, Number.isFinite(frac) ? frac : 0));
    m.val.style.strokeDashoffset = m.largo * (1 - f);
    m.val.style.stroke = color;
    m.txt.textContent = n(valor, dec);
    m.uni.textContent = unidad || "";
    m.caja.className = "medidor" + (clase ? " " + clase : "");
  }

  // ------------------------------------------------------------------ PROCESO
  let ultimoProceso = null;
  async function cargarProceso() {
    const d = await api("/proceso");
    ultimoProceso = d;
    if (!d.ts) { $("banner-titulo").textContent = "Sin datos todavía"; $("banner-accion").textContent = "Inicia la simulación o conecta la planta."; return; }
    pintarCabecera(d);
    pintarBanner(d);
    const porTag = Object.fromEntries(d.sensores.map((s) => [s.tag, s]));
    // Medidores
    [...MED_IZQ, ...MED_DER].forEach(([tag]) => {
      if (tag === "AE") {
        const v = d.vigilancia;
        if (!v || !d.en_marcha) { pintarMedidor("AE", null, 0, COLOR.gris, "error", 3, ""); return; }
        const sobre = v.umbral && v.error > v.umbral;
        pintarMedidor("AE", v.error, v.umbral ? v.error / (v.umbral * 4) : 0, sobre ? COLOR.rojo : COLOR.verde, "error", 3, sobre ? "fuera" : "");
        return;
      }
      const s = porTag[tag];
      if (!s) { pintarMedidor(tag, null, 0, COLOR.gris, "", 1, ""); return; }
      const [lo, hi] = s.rango_min !== null && s.rango_max !== null ? [s.rango_min, s.rango_max] : (RANGO_DEFECTO[tag] || [0, 100]);
      const apagado = !d.en_marcha && SOLO_MARCHA.has(tag);
      const color = s.fuera_de_rango ? COLOR.rojo : s.senalado_ae ? COLOR.morado : apagado ? COLOR.gris : COLOR.verde;
      pintarMedidor(tag, s.valor, (s.valor - lo) / (hi - lo || 1), color, s.unidad,
        DECIMALES[tag] ?? 1, s.fuera_de_rango ? "fuera" : s.senalado_ae ? "ae" : "");
    });
    pintarDiagrama(d, porTag);
    pintarDiagnostico(d);
    pintarAlarmasCard($("card-alarmas").querySelector(".contenido"), d.alarmas_activas, d.ts);
    pintarRiesgo(d.riesgo);
    pintarIndicadores(d.indicadores);
    actualizarContador(d.alarmas_activas.length);
    await pintarTendencias(d, porTag);
  }

  function textoOrigen(a) {
    if (!a) return "";
    if (a.origen === "regla fija") return "Detectada por una regla fija sobre el valor del sensor.";
    return "Identificado por el " + (a.origen_texto || "modelo") + ".";
  }
  function pintarBanner(d) {
    const p = d.panel, b = $("banner");
    b.className = "banner " + (p.color || "gris");
    $("banner-titulo").textContent = p.titulo;
    const alarma = p.nivel === "alarma" ? d.alarmas_activas[0] : null;
    $("banner-accion").textContent = p.accion || (p.nivel === "normal" ? "Todas las variables dentro de su banda normal y sin anomalías." : "");
    $("banner-origen").textContent = alarma ? textoOrigen(alarma)
      : p.nivel === "normal" ? "Diagnóstico y vigilancia sin hallazgos." : p.nivel === "aviso" ? "Detectado por el autoencoder (vigilancia)." : "";
    $("banner-desde").textContent = p.desde ? `Activa desde ${fHora(p.desde)} (${fFecha(p.desde)}), hace ${duracion(minutosEntre(p.desde, d.ts))}` : "";
    $("banner-ver").hidden = p.nivel !== "alarma";
  }

  function pintarDiagrama(d, porTag) {
    const tipo = TIPO_TEXTO[d.tipo_asfalto] || "";
    $("diagrama-titulo").textContent = "Planta de emulsión / Línea de molienda / " + (d.estado_texto || "") +
      (d.en_marcha && tipo ? `, ${tipo}` : "");
    $("pid-fabricando").textContent = d.estado === "produccion" ? `Fabricando: emulsión con asfalto ${tipo}`
      : d.estado === "limpieza" ? "Limpieza de línea con agua y aire" : "";
    $("pid").classList.toggle("pid-activo", !!d.en_marcha);
    const valores = Object.fromEntries(Object.entries(porTag).map(([k, s]) => [k, s.valor]));
    if (porTag.AMP_niv_emulsion_dep) valores.NIVEL_EMULSION = Math.max(0, Math.min(100, (porTag.AMP_niv_emulsion_dep.valor - 4) / 16 * 100));
    document.querySelectorAll("#pid [data-tag]").forEach((t) => {
      const v = valores[t.dataset.tag];
      t.textContent = v === undefined || v === null ? "" : `${t.dataset.pre || ""}${n(v, Number(t.dataset.dec))} ${t.dataset.uni || ""}`.trim();
      const s = porTag[t.dataset.tag];
      t.classList.toggle("marcado", !!(s && s.fuera_de_rango));
      t.classList.toggle("marcado-ae", !!(s && s.senalado_ae));
    });
    document.querySelectorAll("#pid [data-nivel]").forEach((r) => {
      const v = valores[r.dataset.nivel];
      const p = v === undefined || v === null ? 0 : Math.max(0, Math.min(100, v)) / 100;
      const alto = Number(r.dataset.alto), y0 = Number(r.dataset.y0);
      r.setAttribute("y", (y0 + alto * (1 - p)).toFixed(1));
      r.setAttribute("height", Math.max(0, alto * p).toFixed(1));
    });
    document.querySelectorAll("#pid .equipo").forEach((g) => {
      const tags = (g.dataset.tags || "").split(",");
      g.classList.toggle("fuera", tags.some((t) => porTag[t] && porTag[t].fuera_de_rango));
      g.classList.toggle("ae", tags.some((t) => porTag[t] && porTag[t].senalado_ae));
    });
    const aire = porTag.VAL_aire_linea ? porTag.VAL_aire_linea.valor : null;
    $("pid-valvula").textContent = aire === null ? "" : aire >= 0.5 ? "aire abierto" : "aire cerrado";
    $("pid-intercambiador").textContent = d.tipo_asfalto === "plastomerico" && d.en_marcha ? "en uso (plastomérico)" : "sin uso";
  }

  function pintarDiagnostico(d) {
    const c = $("card-diagnostico").querySelector(".contenido");
    if (!d.en_marcha) { vaciar(c, el("p", { clase: "sub" }, "El molino no está en marcha: los modelos se aplican durante la producción y la limpieza.")); return; }
    const g = d.diagnostico, v = d.vigilancia;
    const hijos = [el("p", { clase: "sub" }, "Identificación de fallas (LightGBM → LightGBM)")];
    if (g) {
      const color = g.falla ? (g.falla === "Anomalia_Desconocida" ? "morado" : "rojo") : "verde";
      hijos.push(el("div", { clase: "estado-linea" }, el("span", { clase: "punto " + color }), g.falla ? g.titulo : "Normal"));
    } else hijos.push(el("p", { clase: "vacio" }, "Esperando el resultado del modelo…"));
    hijos.push(el("p", { clase: "sub" }, "Autoencoder (anomalías y degradación)"));
    if (v) {
      hijos.push(el("div", { clase: "estado-linea" }, el("span", { clase: "punto " + (v.alerta ? "morado" : "verde") }),
        `Error ${n(v.error, 3)}`, el("small", { clase: "sub", style: "font-family:var(--fuente);font-size:14px;margin:0" }, `umbral ${n(v.umbral, 3)}`)));
      // escala logarítmica de 0,01 a 100
      const pos = (x) => Math.max(0, Math.min(100, (Math.log10(Math.max(x, 0.01)) + 2) / 4 * 100));
      const barra = el("div", { clase: "barra-ae" }, el("div", { clase: "relleno", style: `width:${pos(v.error)}%` }),
        el("div", { clase: "marca", style: `left:${pos(v.umbral || 0.01)}%`, title: "umbral" }));
      hijos.push(barra, el("div", { clase: "escala" }, el("span", {}, "0,01"), el("span", {}, "umbral"), el("span", {}, "100")));
      if (v.sensores && v.sensores.length) {
        const nombres = Object.fromEntries((ultimoProceso.sensores || []).map((s) => [s.tag, s.nombre]));
        hijos.push(el("ul", { clase: "lista-sens" }, v.sensores.slice(0, 3).map((s) =>
          el("li", {}, el("span", {}, nombres[s.tag] || s.tag), el("span", {}, s.porcentaje !== null && s.porcentaje !== undefined ? `${n(s.porcentaje, 0)} %` : "")))));
      }
    }
    if (g && g.falla) {
      hijos.push(g.confirmado_por_autoencoder
        ? el("div", { clase: "confirmado" }, "Diagnóstico confirmado: los sensores señalados por el autoencoder coinciden con la falla identificada.")
        : el("div", { clase: "sin-confirmar" }, "El autoencoder todavía no confirma la anomalía: se espera la persistencia de 3 de 5 minutos."));
    }
    vaciar(c, hijos);
  }

  function itemAlarma(a, ts) {
    return el("div", { clase: "alarma-item" },
      el("div", { clase: "cab" }, el("span", {}, a.mensaje), el("span", { clase: "etiqueta " + a.prioridad }, a.prioridad[0].toUpperCase() + a.prioridad.slice(1))),
      el("p", {}, `Desde ${fHora(a.inicio)} del ${fFecha(a.inicio)}, ${duracion(minutosEntre(a.inicio, ts))}. ` +
        (a.origen === "regla fija" ? "Regla fija." : `Identificado por el ${a.origen_texto}.`)));
  }
  function pintarAlarmasCard(c, lista, ts) {
    vaciar(c, lista.length ? lista.slice(0, 4).map((a) => itemAlarma(a, ts)) : [el("p", { clase: "vacio" }, "Sin alarmas activas.")]);
  }
  function actualizarContador(k) { const c = $("cont-alarmas"); c.textContent = k; c.hidden = !k; }

  function pintarRiesgo(lista) {
    const c = $("card-riesgo").querySelector(".contenido");
    const por = Object.fromEntries((lista || []).map((r) => [r.falla, r]));
    if (!lista || !lista.length) {
      vaciar(c, el("p", { clase: "vacio" }, "Sin predicción reciente: el modelo predictivo emite cada hora con el molino en marcha."));
      return;
    }
    vaciar(c, FALLAS.map(([codigo, corto]) => {
      const r = por[codigo];
      const etq = !r ? el("span", { clase: "riesgo sd" }, "sin dato")
        : r.riesgo_en ? el("span", { clase: "riesgo r" + r.riesgo_en }, "Riesgo en " + TEXTO_HZ[r.riesgo_en])
          : el("span", { clase: "riesgo no" }, "Sin riesgo");
      return el("div", { clase: "riesgo-fila" }, el("span", {}, corto), etq);
    }));
  }

  function pintarIndicadores(k) {
    const c = $("card-indicadores").querySelector(".contenido");
    if (!k) { vaciar(c); return; }
    const t = (et, num, det, fuera) => el("div", { clase: "indicador" }, el("div", { clase: "et" }, et),
      el("div", { clase: "num" + (fuera ? " fuera" : "") }, num), el("div", { clase: "det" }, det));
    vaciar(c,
      el("div", { clase: "indicadores" },
        t("Relación betún / solución", k.relacion_betun_pct === null ? "—" : `${n(k.relacion_betun_pct, 1)} %`,
          `Objetivo ${k.relacion_objetivo[0]}–${k.relacion_objetivo[1]} %`, k.relacion_fuera),
        t("Producción", `${n(k.produccion_t, 1)} t`, "Emulsión del día"),
        t("Marcha sin anomalía", k.marcha_sin_anomalia_pct === null ? "—" : `${n(k.marcha_sin_anomalia_pct, 1)} %`, "Del tiempo en marcha"),
        t("Energía del motor", `${n(k.energia_kwh, 0)} kWh`, "Estimada (380 V)")),
      el("p", { clase: "nota" }, `${n(k.horas_marcha, 1)} h de molino en marcha hoy`));
  }

  async function pintarTendencias(d, porTag) {
    let tags = TENDENCIA_DEFECTO;
    const falla = (d.alarmas_activas.find((a) => a.falla) || {}).falla || (d.diagnostico && d.diagnostico.falla);
    if (falla && TENDENCIA_FALLA[falla]) tags = TENDENCIA_FALLA[falla];
    else if (falla === "Anomalia_Desconocida" && d.vigilancia && d.vigilancia.sensores.length) {
      tags = d.vigilancia.sensores.slice(0, 3).map((s) => s.tag).filter((t) => porTag[t]);
      while (tags.length < 3) tags.push(TENDENCIA_DEFECTO[tags.length]);
    }
    const hasta = new Date(d.ts), desde = new Date(hasta.getTime() - 12 * 3600e3);
    let serie;
    try {
      serie = await api("/lecturas/serie", { params: { tags: tags.join(","), paso: "5min", desde: desde.toISOString(), hasta: hasta.toISOString() } });
    } catch { return; }
    const porSerie = Object.fromEntries(serie.series.map((s) => [s.tag, s]));
    const tarjetas = $("tendencias").querySelectorAll(".tendencia");
    tags.forEach((tag, i) => {
      const t = tarjetas[i], s = porTag[tag] || {}, datos = porSerie[tag];
      t.querySelector("h3").textContent = (s.nombre || tag).toUpperCase();
      const v = t.querySelector(".tend-valor");
      vaciar(v, n(s.valor, DECIMALES[tag] ?? 1), el("small", {}, s.unidad || ""));
      v.classList.toggle("fuera", !!s.fuera_de_rango);
      t.querySelector(".nota").textContent = "Últimas 12 h · verde: banda normal del modo actual";
      const g = grafico(t.querySelector(".grafico"));
      if (!g) return;
      const pts = datos ? datos.puntos.map((p) => [p.t, p.prom]) : [];
      const banda = s.normal_min !== null && s.normal_min !== undefined && s.normal_max !== null
        ? [[{ yAxis: s.normal_min }, { yAxis: s.normal_max }]] : [];
      g.setOption({
        animation: false, grid: { left: 44, right: 8, top: 8, bottom: 22 },
        tooltip: { trigger: "axis", valueFormatter: (x) => n(x, DECIMALES[tag] ?? 2) },
        xAxis: { type: "time", ...EJE, axisLabel: { color: COLOR.texto2, hideOverlap: true, formatter: (x) => fHora(x) }, splitLine: { show: false } },
        yAxis: { type: "value", scale: true, ...EJE },
        series: [{ type: "line", data: pts, showSymbol: false, lineStyle: { color: COLOR.texto, width: 1.6 },
          markArea: { silent: true, itemStyle: { color: "rgba(69,196,106,.13)" }, data: banda } }],
      }, true);
    });
  }

  // ------------------------------------------------------------------ PREDICCIÓN
  async function cargarPrediccion() {
    const d = await api("/prediccion");
    const tb = $("tabla-semaforo");
    textoBarra.prediccion = d.emitida ? `Predicción emitida a las ${fHora(d.emitida)} del ${fFecha(d.emitida)}` : "Todavía no hay una predicción reciente";
    if (!d.fallas.length) { filaVacia(tb, 7, "Sin predicción reciente. El modelo predictivo emite cada hora con el molino en marcha."); }
    else {
      const por = Object.fromEntries(d.fallas.map((f) => [f.falla, f]));
      vaciar(tb, FALLAS.filter(([c]) => por[c]).map(([codigo, corto]) => {
        const f = por[codigo], tendencia = /tendencia/i.test(f.metodo || "");
        const celdas = HORIZONTES.map(([hz]) => {
          const h = f.horizontes[hz] || {};
          const det = tendencia ? (h.dias_estimados !== null && h.dias_estimados !== undefined ? `≈ ${n(h.dias_estimados, 1)} días`
            : f.horizontes["24h"] && f.horizontes["24h"].dias_estimados ? `≈ ${n(f.horizontes["24h"].dias_estimados, 1)} días` : "sin tendencia")
            : `${pct(h.probabilidad)} (umbral ${pct(h.umbral)})`;
          return el("td", { clase: "celda " + (h.alerta ? "alto-" + hz : "bajo") },
            el("span", { clase: "nivel-txt" }, h.alerta ? "ALTO" : "bajo"), el("span", { clase: "det" }, det));
        });
        return el("tr", {}, el("td", { clase: "fuerte" }, corto), el("td", {}, tendencia ? "Tendencia" : (f.metodo || "LightGBM")),
          celdas, el("td", {}, f.dias_desde_intervencion === null ? "—" : `${n(f.dias_desde_intervencion, 1)} días`),
          el("td", {}, f.alto_en.length ? f.accion || "" : ""));
      }));
    }
    await cargarEvolucion();
  }
  async function cargarEvolucion() {
    const hz = $("evo-horizonte").value;
    const d = await api("/prediccion/evolucion", { params: { horizonte: hz, dias: 7 } });
    $("evo-mensaje").textContent = d.mensaje || "";
    const g = grafico($("graf-evolucion")); if (!g) return;
    const colores = { Filtro_Obstruido: COLOR.rojo, Sobrecarga_Motor_Por_Asfalto_Frio: COLOR.azul, Advertencia_Radar_Sucio_Betun: COLOR.morado };
    g.setOption({
      animation: false, grid: { left: 52, right: 16, top: 16, bottom: 52 },
      legend: { bottom: 0, left: 0, textStyle: { color: COLOR.texto2 }, icon: "rect", itemHeight: 4 },
      tooltip: { trigger: "axis", valueFormatter: (x) => pct(x) },
      xAxis: { type: "time", ...EJE, axisLabel: { color: COLOR.texto2, hideOverlap: true, formatter: (x) => fFecha(x).slice(0, 5) } },
      yAxis: { type: "value", min: 0, max: 1, ...EJE, axisLabel: { color: COLOR.texto2, formatter: (x) => `${x * 100} %` } },
      series: d.series.map((s) => ({
        name: CORTO[s.falla] || s.titulo, type: "line", showSymbol: false, data: s.puntos.map((p) => [p.t, p.probabilidad]),
        lineStyle: { width: 2, color: colores[s.falla] }, itemStyle: { color: colores[s.falla] },
        markLine: s.umbral === null ? undefined : { silent: true, symbol: "none", label: { show: false },
          lineStyle: { type: "dashed", color: colores[s.falla], opacity: .7 }, data: [{ yAxis: s.umbral }] },
      })),
    }, true);
  }
  $("evo-horizonte").addEventListener("change", () => cargarEvolucion().catch(() => {}));

  // ------------------------------------------------------------------ ALARMAS
  async function cargarAlarmas() {
    const d = await api("/alarmas/pantalla");
    const act = $("lista-activas");
    vaciar(act, d.activas.length ? d.activas.map((a) => itemAlarma(a, d.ts)) : [el("p", { clase: "vacio" }, "Sin alarmas activas.")]);
    actualizarContador(d.activas.length);
    const tb = $("tabla-historial");
    if (!d.historial.length) { filaVacia(tb, 6, "Todavía no hay alarmas registradas en este periodo."); return; }
    vaciar(tb, d.historial.map((a) => el("tr", {},
      el("td", {}, fFechaHora(a.inicio)),
      a.activa ? el("td", { clase: "activa" }, "activa") : el("td", {}, fFecha(a.fin) === fFecha(a.inicio) ? fHora(a.fin) : fFechaHora(a.fin)),
      el("td", {}, a.mensaje),
      el("td", {}, el("span", { clase: "etiqueta " + a.prioridad }, a.prioridad[0].toUpperCase() + a.prioridad.slice(1))),
      el("td", {}, a.origen === "regla fija" ? "Regla fija" : "Modelo"),
      el("td", {}, duracion(a.duracion_min)))));
  }

  // ------------------------------------------------------------------ SALUD
  async function cargarSalud() {
    const d = await api("/salud-equipo", { params: { dias: 45 } });
    const dias = d.dias || [];
    const hoy = dias[dias.length - 1];
    const kpi = (et, num, det) => el("div", { clase: "kpi" }, el("div", { clase: "et" }, et), el("div", { clase: "num" }, num), el("div", { clase: "det" }, det));
    const tendencia = dias.length >= 3 ? (dias[dias.length - 1].error_medio > dias[dias.length - 3].error_medio ? "Tendencia al alza" : "Estable o a la baja") : "Pocos días con datos";
    vaciar($("kpis-salud"),
      kpi("Error medio del último día", hoy ? n(hoy.error_medio, 3) : "—", hoy ? (hoy.sobre_umbral ? "Sobre el umbral" : "Bajo el umbral") : "Sin datos del autoencoder"),
      kpi("Umbral de anomalía", d.umbral === null ? "—" : n(d.umbral, 3), "Percentil 99 de operación sana"),
      kpi("Días sobre el umbral", String(d.dias_sobre_umbral || 0), tendencia));
    const g = grafico($("graf-salud"));
    if (g) {
      g.setOption({
        animation: false, grid: { left: 56, right: 20, top: 16, bottom: 30 },
        tooltip: { trigger: "axis", valueFormatter: (x) => n(x, 3) },
        xAxis: { type: "category", data: dias.map((x) => fDia(x.dia)), ...EJE, splitLine: { show: false } },
        yAxis: { type: "log", min: 0.01, max: (v) => Math.max(v.max, (d.umbral || 0) * 1.5, 0.1), ...EJE, axisLabel: { color: COLOR.texto2, formatter: (x) => n(x, x < 1 ? 2 : 0) } },
        series: [{ type: "line", data: dias.map((x) => ({ value: Math.max(x.error_medio || 0.01, 0.01),
          itemStyle: { color: x.sobre_umbral ? COLOR.rojo : COLOR.texto } })),
          symbol: "circle", symbolSize: 6, lineStyle: { color: COLOR.texto, width: 1.6 },
          markLine: d.umbral === null ? undefined : { silent: true, symbol: "none", label: { show: false },
            lineStyle: { type: "dashed", color: COLOR.naranja }, data: [{ yAxis: d.umbral }] } }],
      }, true);
    }
    const tb = $("tabla-salud");
    const recientes = dias.filter((x) => x.minutos_marcha > 0).slice(-10).reverse();
    if (!recientes.length) { filaVacia(tb, 4, "Sin días con el molino en marcha y resultados del autoencoder. Se completan a medida que avanza la simulación."); return; }
    vaciar(tb, recientes.map((x) => el("tr", {}, el("td", {}, fDia(x.dia)),
      el("td", { clase: x.sobre_umbral ? "rojo" : "fuerte" }, n(x.error_medio, 3)),
      el("td", {}, String(x.minutos_marcha)), el("td", {}, String(x.minutos_anomalia)))));
  }

  // ------------------------------------------------------------------ MANTENIMIENTO
  let bitacoraCompleta = false;
  $("btn-bitacora").addEventListener("click", () => { bitacoraCompleta = true; cargarMantenimiento().catch(() => {}); });
  async function cargarMantenimiento() {
    const d = await api("/mantenimiento/pantalla");
    const kpi = (et, num, det) => el("div", { clase: "kpi" }, el("div", { clase: "et" }, et), el("div", { clase: "num" }, num), el("div", { clase: "det" }, det));
    const filtro = d.equipos.find((e) => e.falla === "Filtro_Obstruido") || {};
    vaciar($("kpis-mant"),
      kpi("Mantenimiento planificado", d.pct_planificado === null ? "—" : `${n(d.pct_planificado, 0)} %`, "Preventivas sobre el total"),
      kpi("Intervenciones", String(d.total_intervenciones || 0), "Registradas hasta la fecha simulada"),
      kpi("MTBF del filtro", filtro.mtbf_dias ? `${n(filtro.mtbf_dias, 0)} días` : "—", "Entre correctivas"));
    vaciar($("tabla-equipos"), d.equipos.map((e) => el("tr", {},
      el("td", { clase: "fuerte" }, e.equipo), el("td", {}, String(e.correctivas)), el("td", {}, String(e.preventivas)),
      el("td", {}, e.mtbf_dias ? `${n(e.mtbf_dias, 0)} días` : "—"), el("td", {}, fFechaHora(e.ultima_intervencion)),
      el("td", {}, e.dias_desde === null ? "—" : `${n(e.dias_desde, 1)} días`),
      el("td", {}, e.riesgo_15d === null || e.riesgo_15d === undefined ? el("span", { clase: "riesgo sd" }, "sin predicción")
        : e.riesgo_15d ? el("span", { clase: "riesgo r5d" }, "Riesgo en 15 días") : el("span", { clase: "riesgo no" }, "Sin riesgo")))));
    const tb = $("tabla-bitacora");
    if (!d.bitacora.length) { filaVacia(tb, 4, "Sin registros hasta la fecha simulada."); return; }
    const todas = bitacoraCompleta || d.bitacora.length <= 15;
    $("btn-bitacora").hidden = todas;
    vaciar(tb, (todas ? d.bitacora : d.bitacora.slice(0, 15)).map((b) => el("tr", {}, el("td", {}, fFechaHora(b.fecha_inicio)), el("td", {}, b.componente || "—"),
      el("td", {}, el("span", { clase: "etiqueta " + (b.tipo === "preventivo" ? "preventiva" : "correctiva") }, b.tipo === "preventivo" ? "Preventiva" : "Correctiva")),
      el("td", {}, b.descripcion || ""))));
  }

  // ------------------------------------------------------------------ USUARIOS (administrador)
  function msgUsuarios(texto, tipo) { const m = $("msg-usuarios"); m.className = "mensaje " + tipo; m.textContent = texto; m.hidden = !texto; }
  async function accionUsuario(fn, ok) {
    try { await fn(); msgUsuarios(ok, "ok"); await cargarUsuarios(); } catch (e) { msgUsuarios(e.message, "error"); }
  }
  async function cargarUsuarios() {
    if (!esAdmin) return;
    const lista = await api("/usuarios");
    const tb = $("tabla-usuarios");
    vaciar(tb, lista.map((u) => {
      const yo = u.id === usuario.id;
      const rol = el("select", { "aria-label": "Rol de " + u.nombre, disabled: yo, onchange: (e) =>
        accionUsuario(() => api(`/usuarios/${u.id}`, { metodo: "PATCH", cuerpo: { rol: e.target.value } }), `Rol de ${u.email} actualizado.`) },
        el("option", { value: "operador", selected: u.rol === "operador" }, "Operador"),
        el("option", { value: "administrador", selected: u.rol === "administrador" }, "Administrador"));
      const estado = !u.activo ? "Inactivo" : u.bloqueado ? "Bloqueado" : u.debe_cambiar_clave ? "Clave temporal" : "Activo";
      const acciones = el("div", { clase: "acciones-fila" },
        el("button", { clase: "btn btn-chico", disabled: yo, onclick: () => accionUsuario(() =>
          api(`/usuarios/${u.id}`, { metodo: "PATCH", cuerpo: { activo: !u.activo } }), `${u.email} ${u.activo ? "desactivado" : "activado"}.`) },
        u.activo ? "Desactivar" : "Activar"),
        el("button", { clase: "btn btn-chico", onclick: () => {
          const clave = window.prompt(`Contraseña temporal para ${u.email} (8 a 72 caracteres, con letras y números):`);
          if (clave) accionUsuario(() => api(`/usuarios/${u.id}/restablecer-clave`, { metodo: "POST", cuerpo: { clave_temporal: clave } }), `Contraseña temporal asignada a ${u.email}.`);
        } }, "Restablecer clave"),
        el("button", { clase: "btn btn-chico btn-peligro", disabled: yo, onclick: () => {
          if (window.confirm(`¿Eliminar a ${u.email}? Si tiene registros asociados, desactívelo en su lugar.`))
            accionUsuario(() => api(`/usuarios/${u.id}`, { metodo: "DELETE" }), `${u.email} eliminado.`);
        } }, "Eliminar"));
      return el("tr", {}, el("td", { clase: "fuerte" }, u.nombre + (yo ? " (usted)" : "")), el("td", {}, u.email), el("td", {}, rol),
        el("td", {}, estado), el("td", {}, u.ultimo_acceso ? fFechaHora(u.ultimo_acceso) : "—"), el("td", {}, acciones));
    }));
    try {
      const aud = await api("/usuarios/auditoria", { params: { limite: 60 } });
      vaciar($("tabla-auditoria"), aud.map((a) => el("tr", {}, el("td", {}, fFechaHora(a.fecha)), el("td", {}, a.email || "—"),
        el("td", {}, a.ip || "—"), el("td", {}, a.accion), el("td", {}, a.detalle || ""))));
    } catch {}
  }
  $("btn-nuevo-usuario").addEventListener("click", () => { $("form-usuario").hidden = false; $("u-nombre").focus(); });
  $("u-cancelar").addEventListener("click", () => { $("form-usuario").hidden = true; });
  $("form-usuario").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const cuerpo = { nombre: $("u-nombre").value.trim(), email: $("u-email").value.trim(), rol: $("u-rol").value, clave_temporal: $("u-clave").value };
    accionUsuario(async () => { await api("/usuarios", { metodo: "POST", cuerpo }); $("form-usuario").reset(); $("form-usuario").hidden = true; },
      `Usuario ${cuerpo.email} creado. Deberá cambiar la contraseña en su primer ingreso.`);
  });

  // ------------------------------------------------------------------ SIMULACIÓN
  let sim = null, opciones = null;
  const textoBarra = {
    proceso: "", prediccion: "", alarmas: "Solo consulta: las alarmas se informan, no se gestionan",
    salud: "Índice de salud calculado con el error del autoencoder", mantenimiento: "Bitácora de mantenimiento en solo lectura",
    simulacion: "", usuarios: "Gestión de usuarios y roles",
  };
  async function controlar(accion, valor) {
    try { sim = await api("/simulacion", { metodo: "POST", cuerpo: { accion, valor: valor || null } }); pintarSim(); avisar(""); }
    catch (e) { avisar(e.message); }
  }
  async function cargarOpciones() {
    try { opciones = await api("/simulacion/opciones"); }
    catch (e) { $("sim-texto").textContent = "Simulador no disponible: " + e.message; $("sim-texto").classList.add("error"); return; }
    vaciar($("sim-velocidad"), opciones.velocidades.map((v) => el("option", { value: v.clave }, v.texto)));
    vaciar($("sim-modo"), el("option", { value: "" }, "Calendario real (2026)"), opciones.modos.map((m) => el("option", { value: m.clave }, m.texto)));
    vaciar($("sim-ir"), el("option", { value: "" }, "Elegir…"),
      el("optgroup", { label: "Inicio de mes" }, opciones.ir_a.meses.map((m) => el("option", { value: m.fecha }, m.etiqueta))),
      el("optgroup", { label: "Antes de una falla real" }, opciones.ir_a.antes_de_falla.map((m) => el("option", { value: m.fecha }, m.etiqueta))));
    vaciar($("sim-escenario"), el("option", { value: "" }, "Ninguna (datos reales)"),
      el("optgroup", { label: "Fallas conocidas" }, opciones.escenarios.filter((e) => e.categoria === "conocida").map((e) => el("option", { value: e.clave }, e.nombre))),
      el("optgroup", { label: "Fallas que ningún modelo vio" }, opciones.escenarios.filter((e) => e.categoria !== "conocida").map((e) => el("option", { value: e.clave }, e.nombre))));
    const boton = (e) => el("button", { clase: "btn", "data-esc": e.clave, title: e.descripcion, onclick: () =>
      controlar("escenario", sim && sim.escenario && sim.escenario.clave === e.clave ? "" : e.clave) }, e.nombre);
    vaciar($("esc-conocidas"), opciones.escenarios.filter((e) => e.categoria === "conocida").map(boton));
    vaciar($("esc-nuevas"), opciones.escenarios.filter((e) => e.categoria !== "conocida").map(boton));
    vaciar($("modos"), el("button", { clase: "btn", "data-modo": "", onclick: () => controlar("modo", "") }, "Calendario real (2026)"),
      opciones.modos.map((m) => el("button", { clase: "btn", "data-modo": m.clave, onclick: () => controlar("modo", m.clave) }, m.texto)));
    pintarSim();
  }
  $("sim-play").addEventListener("click", () => controlar(sim && sim.corriendo ? "pausar" : "iniciar"));
  $("sim-velocidad").addEventListener("change", (e) => controlar("velocidad", e.target.value));
  $("sim-saltar").addEventListener("change", (e) => controlar("saltar_paradas", e.target.checked ? "1" : "0"));
  $("sim-modo").addEventListener("change", (e) => controlar("modo", e.target.value));
  $("sim-escenario").addEventListener("change", (e) => controlar("escenario", e.target.value));
  $("sim-ir").addEventListener("change", (e) => { const v = e.target.value; e.target.value = ""; if (v) controlar("ir_a", v); });
  $("btn-quitar-falla").addEventListener("click", () => controlar("escenario", ""));

  function pintarSim() {
    if (!sim) return;
    const play = $("sim-play");
    play.textContent = sim.corriendo ? "Pausar" : "Iniciar";
    if (opciones) {
      $("sim-velocidad").value = sim.velocidad;
      $("sim-saltar").checked = !!sim.saltar_paradas;
      $("sim-saltar").disabled = !!sim.modo;
      $("sim-modo").value = sim.modo || "";
      $("sim-escenario").value = sim.escenario ? sim.escenario.clave : "";
    }
    document.querySelectorAll("[data-esc]").forEach((b) => b.classList.toggle("activo", !!(sim.escenario && sim.escenario.clave === b.dataset.esc)));
    document.querySelectorAll("[data-modo]").forEach((b) => b.classList.toggle("activo", (sim.modo || "") === b.dataset.modo));
    const esc = sim.escenario ? `falla inyectada ${sim.escenario.nombre}, desarrollo ${n(sim.escenario.progreso * 100, 0)} %` : "sin falla inyectada";
    textoBarra.proceso = `Etiqueta real: ${(sim.etiqueta_real || "—").replace(/_/g, " ")}`;
    textoBarra.simulacion = `Modo demostración: ${esc}`;
    const pref = sim.modo ? "Modo fijo de funcionamiento." : "Reproducción del año 2026.";
    const t = $("sim-texto");
    t.classList.toggle("error", !!sim.error);
    t.textContent = sim.preparando ? sim.preparando + "…" : sim.error ? "Error: " + sim.error : `${pref} ${textoBarra[pestana] || ""}`.trim();
    if (sim.aviso) avisar(sim.aviso);
    const dl = $("sim-datos");
    const fila = (a, b) => [el("dt", {}, a), el("dd", {}, b)];
    vaciar(dl, fila("Estado", sim.preparando ? "Preparando: " + sim.preparando : sim.corriendo ? "En marcha" : "En pausa"),
      fila("Fecha simulada", sim.tiempo ? fFechaHora(sim.tiempo) : "—"),
      fila("Saltar paradas", sim.modo ? "No aplica (modo fijo)" : sim.saltar_paradas ? "Sí: detenida, espera y preparación a 1 hora por segundo" : "No"),
      fila("Velocidad", (opciones && (opciones.velocidades.find((v) => v.clave === sim.velocidad) || {}).texto) || sim.velocidad),
      fila("Publicación", sim.publicacion === "iot" ? "AWS IoT Core → Lambda de inferencia → DynamoDB → RDS" : "Local (solo lecturas, sin modelos)"),
      fila("Lecturas publicadas", String(sim.publicados)),
      fila("Etiqueta real del dataset", (sim.etiqueta_real || "—").replace(/_/g, " ")),
      sim.error ? fila("Último error", sim.error) : null);
  }
  async function cargarSim() {
    try { sim = await api("/simulacion"); pintarSim(); } catch {}
  }

  // ------------------------------------------------------------------ ciclo de actualización
  const CARGAS = { proceso: cargarProceso, prediccion: cargarPrediccion, alarmas: cargarAlarmas, salud: cargarSalud,
    mantenimiento: cargarMantenimiento, simulacion: async () => {}, usuarios: cargarUsuarios };
  let cargando = false, pendiente = false;
  async function refrescar(forzar) {
    if (cargando) { pendiente = true; return; }
    cargando = true;
    try {
      if (pestana !== "proceso") {
        try { const est = await api("/estado/actual"); pintarCabecera(est); } catch {}
      }
      if (forzar || pestana !== "usuarios") await CARGAS[pestana]();
      if (sim) pintarSim();
    } catch (e) {
      if (e.estado !== 401) avisar(e.estado === 409 ? e.message : "No se pudo actualizar: " + e.message);
    } finally {
      cargando = false;
      if (pendiente) { pendiente = false; setTimeout(() => refrescar(false), 300); }
    }
  }
  setInterval(() => { if (!document.hidden) refrescar(false); }, 5000);
  setInterval(() => { if (!document.hidden) cargarSim(); }, 2000);

  // Canal en vivo: cuando llega un resultado nuevo se actualiza la pestaña sin esperar los 5 s
  let ws = null, demoraWs = 2000, temporizador = null;
  function conectarWs() {
    try {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/api/ws/telemetria?token=${encodeURIComponent(Sesion.token || "")}`);
    } catch { return; }
    ws.onopen = () => { demoraWs = 2000; $("chip-modelos").title = "Canal en vivo conectado"; };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.topic === "planta/asfalto/molino/resultados") {
        clearTimeout(temporizador); temporizador = setTimeout(() => refrescar(false), 700);
      }
    };
    ws.onclose = () => {
      $("chip-modelos").title = "Actualización periódica cada 5 s";
      setTimeout(conectarWs, demoraWs); demoraWs = Math.min(demoraWs * 2, 60000);
    };
  }
  // API Gateway HTTP no transmite WebSocket: por HTTPS se usa solo la actualización periódica
  if (location.protocol === "http:") conectarWs();

  // Indicador de modelos: verde si hubo un resultado de los modelos en los últimos 5 minutos simulados
  const _cargarProceso = CARGAS.proceso;
  CARGAS.proceso = async () => {
    await _cargarProceso();
    const d = ultimoProceso, chip = $("chip-modelos");
    const activos = d && d.ts && d.en_marcha && (d.diagnostico || d.vigilancia);
    chip.querySelector(".punto").className = "punto " + (activos ? "verde" : "gris");
    chip.querySelector(".txt").textContent = activos ? "Modelos: diagnóstico, vigilancia, predicción" : "Modelos en espera (molino detenido o sin resultados)";
  };

  // ------------------------------------------------------------------ inicio
  cargarSim().then(cargarOpciones);
  mostrar(pestana);
})();
