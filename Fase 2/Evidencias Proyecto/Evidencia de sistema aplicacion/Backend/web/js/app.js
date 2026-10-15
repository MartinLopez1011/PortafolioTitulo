/* Web del sistema de mantenimiento predictivo – molino coloidal MC-01 (QLA) */
(function () {
  "use strict";

  // ------------------------------------------------------------ configuración visual
  const GRUPOS = [
    { codigo: "TK-101", nombre: "Estanque de betún" },
    { codigo: "FT-101", nombre: "Caudal de betún" },
    { codigo: "TK-201", nombre: "Estanque de solución" },
    { codigo: "FT-201", nombre: "Caudal de solución" },
    { codigo: "P-101", nombre: "Bomba de alimentación" },
    { codigo: "F-101", nombre: "Filtro" },
    { codigo: "V-101", nombre: "Válvula de 3 vías y aire" },
    { codigo: "MC-01", nombre: "Molino y motor" },
    { codigo: "E-301", nombre: "Intercambiador de calor" },
    { codigo: "TK-301", nombre: "Estanque de emulsión" },
  ];
  // Variables que describen al instrumento y no al proceso: se muestran plegadas
  const DIAGNOSTICO = new Set(["corriente_lazo", "voltaje", "resistencia", "frecuencia", "eco", "estado", "distancia"]);
  const ESTADOS = {
    produccion: { texto: "Producción", color: "#199e70" },
    preparacion: { texto: "Preparación", color: "#3987e5" },
    limpieza: { texto: "Limpieza", color: "#9085e9" },
    espera: { texto: "Espera", color: "#c98500" },
    detenida: { texto: "Detenida", color: "#4a5468" },
    mantenimiento: { texto: "Mantenimiento", color: "#d95926" },
    falla: { texto: "Falla", color: "#e66767" },
  };
  const ASFALTO = { convencional: "Asfalto convencional", plastomerico: "Asfalto plastomérico", ninguno: "Sin asfalto" };
  const ROLES = { administrador: "Administrador", supervisor: "Supervisor", operador: "Operador", visualizador: "Visualizador" };
  const ACCIONES_AUD = {
    login_ok: "Ingreso", login_fallido: "Ingreso fallido", login_bloqueado: "Ingreso con cuenta bloqueada",
    login_rechazado: "Ingreso de usuario inactivo", cambio_clave: "Cambio de contraseña",
    cambio_clave_fallido: "Cambio de contraseña fallido", usuario_creado: "Usuario creado",
    usuario_modificado: "Usuario modificado", clave_restablecida: "Contraseña temporal asignada",
    alarma_reconocida: "Alarma reconocida", mantenimiento_registrado: "Mantenimiento registrado",
  };
  const PASO_POR_HORAS = { 24: "5min", 72: "15min", 168: "1h", 336: "1h" };
  const SENSORES_INICIALES = ["TEM_son_betum_in", "AMP_vfd_motor_molino", "VIB_vel_motor_molino", "PRE_dif_filtro_bar"];
  const MAX_SENSORES = 6;
  const C = { texto: "#e8ecf3", texto2: "#a9b3c6", tenue: "#7c879c", grilla: "#2a3242", eje: "#3a4456", serie: "#3987e5",
              banda: "rgba(57,135,229,0.18)", normal: "rgba(12,163,12,0.09)", normalBorde: "rgba(12,163,12,0.45)" };

  const estado = {
    usuario: null, fuente: "simulado", vista: "panel", sensores: [], porTag: {}, tiposFalla: [],
    ultima: null, horas: 24, seleccion: [...SENSORES_INICIALES], graficos: [], alarmasActivas: true, temporizador: null,
  };

  // ------------------------------------------------------------ utilidades
  const $ = (id) => document.getElementById(id);
  function toast(texto, tipo = "ok") {
    const t = $("toast");
    t.replaceChildren(el("div", { clase: "mensaje " + tipo, texto }));
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 4500);
  }
  function vacio(contenedor, texto) { contenedor.replaceChildren(el("div", { clase: "vacio", texto })); }
  function mostrarError(contenedor, e) { contenedor.replaceChildren(el("div", { clase: "mensaje error", texto: e.message })); }
  function rangoTexto(s) {
    if (s.normal_min === null && s.normal_max === null) return null;
    const u = s.unidad === "0/1" ? "" : " " + s.unidad;
    if (s.normal_min !== null && s.normal_max !== null) return `Normal entre ${numero(s.normal_min)} y ${numero(s.normal_max)}${u}`;
    return s.normal_min !== null ? `Normal desde ${numero(s.normal_min)}${u}` : `Normal hasta ${numero(s.normal_max)}${u}`;
  }
  function valorTexto(s) {
    if (s.unidad === "0/1") return s.valor === null ? "—" : (Number(s.valor) >= 0.5 ? "Activa" : "Inactiva");
    const abs = Math.abs(Number(s.valor));
    return numero(s.valor, abs >= 1000 ? 0 : abs >= 100 ? 1 : 2);
  }
  function puede(nivel) { return estado.usuario && estado.usuario.nivel >= nivel; }
  function isoLocal(valor) { return valor ? new Date(valor).toISOString() : null; }

  // ------------------------------------------------------------ inicio
  async function iniciar() {
    if (!Sesion.token) { location.replace("/login.html"); return; }
    try {
      estado.usuario = await api("/auth/me");
    } catch { return; }   // api() ya redirige al login si la sesión no es válida
    if (estado.usuario.debe_cambiar_clave) { Sesion.cerrar(); location.replace("/login.html"); return; }

    $("cab-usuario").textContent = estado.usuario.nombre;
    $("cab-rol").textContent = ROLES[estado.usuario.rol] || estado.usuario.rol;
    document.querySelectorAll("[data-nivel]").forEach((n) => { n.hidden = !puede(Number(n.dataset.nivel)); });

    $("btn-salir").addEventListener("click", () => { Sesion.cerrar(); location.replace("/login.html?motivo=salida"); });
    $("sel-fuente").addEventListener("change", (e) => { estado.fuente = e.target.value; cargarVista(); });
    document.querySelectorAll(".nav button").forEach((b) => b.addEventListener("click", () => irA(b.dataset.vista)));
    window.addEventListener("resize", () => estado.graficos.forEach((g) => g.resize()));
    configurarTendencias();
    configurarAlarmas();
    configurarMantenimiento();
    configurarUsuarios();

    try {
      const [sensores, fallas] = await Promise.all([api("/sensores"), api("/tipos-falla")]);
      estado.sensores = sensores;
      sensores.forEach((s) => { estado.porTag[s.tag] = s; });
      estado.tiposFalla = fallas;
      llenarSelectores();
    } catch (e) { toast(e.message, "error"); }

    const inicial = (location.hash || "#panel").slice(1);
    irA(document.querySelector(`.nav button[data-vista="${inicial}"]:not([hidden])`) ? inicial : "panel");
    estado.temporizador = setInterval(() => { if (!document.hidden) actualizarCabecera(); if (estado.vista === "panel") cargarPanel(); }, 60000);
    conectarCanalTiempoReal();
  }

  function irA(vista) {
    estado.vista = vista;
    history.replaceState(null, "", "#" + vista);
    document.querySelectorAll(".nav button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.vista === vista)));
    document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== vista; });
    cargarVista();
  }

  function cargarVista() {
    actualizarCabecera();
    ({ panel: cargarPanel, tendencias: cargarTendencias, alarmas: cargarAlarmas,
       mantenimiento: cargarMantenimiento, usuarios: cargarUsuarios })[estado.vista]();
  }

  // ------------------------------------------------------------ cabecera
  async function actualizarCabecera() {
    try {
      const r = await api("/resumen", { params: { fuente: estado.fuente } });
      estado.ultima = r.ultima_lectura;
      const est = ESTADOS[r.estado];
      const chip = $("cab-estado");
      chip.replaceChildren(el("span", { clase: "punto", style: `background:${est ? est.color : C.tenue}` }),
                           est ? est.texto : "Sin datos");
      $("cab-lectura").textContent = r.ultima_lectura ? "Última lectura " + fechaHora(r.ultima_lectura) : "Sin lecturas";
      const ins = $("insignia-alarmas");
      ins.hidden = !r.alarmas_sin_reconocer;
      ins.textContent = r.alarmas_sin_reconocer || "";
      ins.title = `${r.alarmas_sin_reconocer} sin reconocer`;
      return r;
    } catch (e) { toast(e.message, "error"); return null; }
  }

  // ------------------------------------------------------------ PANEL
  async function cargarPanel() {
    let r, lecturas, pred;
    try {
      [r, lecturas, pred] = await Promise.all([
        api("/resumen", { params: { fuente: estado.fuente } }),
        api("/lecturas/ultimas", { params: { fuente: estado.fuente } }),
        api("/predicciones/ultimas", { params: { fuente: estado.fuente } }),
      ]);
    } catch (e) { mostrarError($("instrumentos"), e); return; }

    const est = ESTADOS[r.estado];
    $("ind-estado").textContent = est ? est.texto : "Sin datos";
    $("ind-asfalto").textContent = r.tipo_asfalto ? (ASFALTO[r.tipo_asfalto] || r.tipo_asfalto) : "";
    $("ind-fuera").textContent = r.sensores_con_datos ? `${r.sensores_fuera_de_rango} de ${r.sensores_con_datos}` : "—";
    $("ind-fuera-det").textContent = r.sensores_fuera_de_rango ? "Revise las lecturas marcadas" : "Todas dentro de su rango";
    $("ind-alarmas").textContent = r.alarmas_activas;
    $("ind-alarmas-det").textContent = r.alarmas_activas ? `${r.alarmas_sin_reconocer} sin reconocer` : "Sin alarmas abiertas";
    $("ind-hora").textContent = r.ultima_lectura ? fmtHora.format(new Date(r.ultima_lectura)) : "—";
    $("ind-fecha").textContent = r.ultima_lectura ? fechaHora(r.ultima_lectura).split(",")[0] + (estado.fuente === "simulado" ? ", datos simulados" : "") : "Sin lecturas para esta fuente";
    $("aviso-detenido").hidden = !(r.estado && r.estado !== "produccion" && r.sensores_fuera_de_rango > 0);

    estado.lecturasActuales = lecturas;
    estado.prediccionesActuales = pred;
    pintarInstrumentos(lecturas);
    pintarPredicciones(pred);
    if (r.ultima_lectura) {
      const hasta = new Date(r.ultima_lectura);
      const desde = new Date(hasta.getTime() - 24 * 3600e3);
      try {
        const hist = await api("/estado/historial", { params: { fuente: estado.fuente, desde: desde.toISOString(), hasta: hasta.toISOString() } });
        graficoEstado($("graf-estado-panel"), hist, desde, hasta);
      } catch (e) { mostrarError($("graf-estado-panel"), e); }
    } else {
      vacio($("graf-estado-panel"), "Sin registros de operación para esta fuente.");
    }
  }

  function pintarInstrumentos(lecturas) {
    const cont = $("instrumentos");
    if (!lecturas.length) {
      vacio(cont, estado.fuente === "real"
        ? "Aún no hay lecturas reales. Aparecerán cuando se conecten los sensores de la planta."
        : "No hay lecturas simuladas. Cargue datos con el script de la carpeta Base de Datos.");
      return;
    }
    const porComp = {};
    lecturas.forEach((l) => { (porComp[l.componente || "Otros"] ||= []).push(l); });
    const orden = [...GRUPOS];
    Object.keys(porComp).forEach((c) => { if (!orden.find((g) => g.codigo === c)) orden.push({ codigo: c, nombre: "" }); });

    const grupos = orden.filter((g) => porComp[g.codigo]).map((g) => {
      const items = porComp[g.codigo];
      const proceso = items.filter((l) => !DIAGNOSTICO.has(l.variable));
      const diag = items.filter((l) => DIAGNOSTICO.has(l.variable));
      const alerta = items.some((l) => l.fuera_de_rango);
      const filas = proceso.map((l) => {
        const rango = rangoTexto(l);
        return el("button", { clase: "lectura" + (l.fuera_de_rango ? " fuera" : ""), type: "button",
                              title: "Ver tendencia de " + l.nombre, onclick: () => irATendencia(l.tag) },
          el("span", { clase: "n", texto: l.nombre }),
          el("span", { clase: "v" }, valorTexto(l), l.unidad !== "0/1" ? el("small", { texto: l.unidad }) : null),
          l.fuera_de_rango
            ? el("span", { clase: "r" }, el("span", { clase: "estado-ico", "aria-hidden": "true", texto: "▲" }), "Fuera de rango. " + rango)
            : rango ? el("span", { clase: "r", texto: rango }) : null);
      });
      const detalle = diag.length ? el("details", {},
        el("summary", { texto: `Señales del instrumento (${diag.length})` }),
        el("div", { clase: "diag" }, diag.flatMap((l) => [
          el("span", { texto: l.nombre + (l.fuera_de_rango ? " (fuera de rango)" : "") }),
          el("span", { texto: `${valorTexto(l)} ${l.unidad === "0/1" ? "" : l.unidad}` })]))) : null;
      return el("section", { clase: "grupo-eq" + (alerta ? " con-alerta" : ""), "aria-label": `${g.codigo} ${g.nombre}` },
        el("header", {}, el("span", { clase: "codigo", texto: g.codigo }), el("span", { clase: "nombre", texto: g.nombre })),
        filas, detalle);
    });
    cont.replaceChildren(...grupos);
  }

  function pintarPredicciones(pred) {
    const cont = $("pred-contenido");
    $("pred-fecha").textContent = pred.length ? "Calculada el " + fechaHora(pred[0].ts) : "";
    if (!pred.length) {
      vacio(cont, "Aún no hay predicciones. Aparecerán aquí cuando los modelos escriban sus resultados en la base de datos.");
      return;
    }
    const HZ = { actual: "Ahora", "24h": "24 horas", "5d": "5 días", "15d": "15 días" };
    const MOD = { diagnostico: "Diagnóstico", autoencoder: "Vigilancia", predictivo: "Predicción" };
    const nivel = (p) => p >= 0.6 ? ["critica", "Alto"] : p >= 0.3 ? ["advertencia", "Medio"] : ["aviso", "Bajo"];
    const filas = pred.map((p) => {
      let riesgo = "—";
      if (p.prob_falla !== null) {
        const [cl, tx] = nivel(Number(p.prob_falla));
        riesgo = el("span", { clase: "sev " + cl }, `${tx} (${numero(Number(p.prob_falla) * 100, 0)} %)`);
      }
      return el("tr", {},
        el("td", { texto: MOD[p.modelo] || p.modelo }),
        el("td", { texto: HZ[p.horizonte] || p.horizonte }),
        el("td", { texto: p.titulo || (p.modelo === "autoencoder" ? "Comportamiento general" : "Sin falla") }),
        el("td", {}, riesgo),
        el("td", { clase: "num", texto: p.indice_salud !== null ? numero(p.indice_salud, 1) : "—" }));
    });
    cont.replaceChildren(el("div", { clase: "tabla-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ["Modelo", "Horizonte", "Falla", "Riesgo", "Índice de salud"].map((t, i) => el("th", { clase: i === 4 ? "num" : null, texto: t })))),
      el("tbody", {}, filas))));
  }

  // ------------------------------------------------------------ gráfico de estados
  function graficoEstado(nodo, hist, desde, hasta, margen = { left: 8, right: 8 }) {
    const previo = echarts.getInstanceByDom(nodo);
    if (previo) previo.dispose();
    if (!hist.length) { vacio(nodo, "Sin registros de operación en el periodo."); return null; }
    const presentes = [...new Set(hist.map((h) => h.estado))];
    const series = presentes.map((est) => ({
      name: (ESTADOS[est] || { texto: est }).texto, type: "custom",
      itemStyle: { color: (ESTADOS[est] || { color: C.tenue }).color },
      encode: { x: [0, 1], y: 2 },
      data: hist.filter((h) => h.estado === est).map((h) => [
        new Date(h.inicio).getTime(), new Date(h.fin).getTime() + 60000, 0, h.minutos, h.tipo_asfalto]),
      renderItem: (params, api) => {
        const ini = api.coord([api.value(0), 0]); const fin = api.coord([api.value(1), 0]);
        const alto = 18;
        const r = echarts.graphic.clipRectByRect(
          { x: ini[0], y: ini[1] - alto / 2, width: Math.max(fin[0] - ini[0] - 1, 1), height: alto },
          { x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height });
        return r && { type: "rect", shape: { ...r, r: 2 }, style: api.style() };
      },
    }));
    const g = echarts.init(nodo, null, { renderer: "canvas" });
    g.setOption({
      animation: false,
      grid: { left: margen.left, right: margen.right, top: 4, bottom: 52, containLabel: false },
      xAxis: { type: "time", min: desde.getTime(), max: hasta.getTime(),
               axisLabel: { color: C.tenue, hideOverlap: true, showMinLabel: false, showMaxLabel: false, formatter: (v) => fmtDiaHora.format(new Date(v)) },
               axisLine: { lineStyle: { color: C.eje } }, splitLine: { show: false } },
      yAxis: { type: "value", show: false, min: -1, max: 1 },
      legend: { bottom: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: C.texto2 } },
      tooltip: { trigger: "item", backgroundColor: "#232b3d", borderColor: "#2e3646", textStyle: { color: C.texto },
        formatter: (p) => {
          const v = p.value;
          const asf = ASFALTO[v[4]] || "";
          return `<b>${p.seriesName}</b><br>${fmtDiaHora.format(new Date(v[0]))} a ${fmtHora.format(new Date(v[1]))}<br>${v[3]} min${asf ? "<br>" + asf : ""}`;
        } },
      series,
    });
    return g;
  }

  // ------------------------------------------------------------ TENDENCIAS
  function llenarSelectores() {
    const sel = $("sel-sensor");
    const porComp = {};
    estado.sensores.forEach((s) => { (porComp[s.componente || "Otros"] ||= []).push(s); });
    const orden = GRUPOS.map((g) => g.codigo).concat(Object.keys(porComp).filter((c) => !GRUPOS.find((g) => g.codigo === c)));
    sel.replaceChildren(...orden.filter((c) => porComp[c]).map((c) => {
      const g = GRUPOS.find((x) => x.codigo === c);
      return el("optgroup", { label: g ? `${c} ${g.nombre}` : c },
        porComp[c].map((s) => el("option", { value: s.tag, texto: `${s.nombre} (${s.unidad})${s.origen === "real" ? ", sensor real" : ""}` })));
    }));
    const fallas = $("m-falla");
    fallas.replaceChildren(el("option", { value: "", texto: "Sin falla asociada" }),
      ...estado.tiposFalla.map((f) => el("option", { value: f.codigo, texto: f.titulo })));
  }

  function configurarTendencias() {
    $("btn-agregar").addEventListener("click", () => {
      const tag = $("sel-sensor").value;
      if (!tag || estado.seleccion.includes(tag)) return;
      if (estado.seleccion.length >= MAX_SENSORES) { toast(`Puede comparar hasta ${MAX_SENSORES} sensores a la vez. Quite uno para agregar otro.`, "info"); return; }
      estado.seleccion.push(tag);
      cargarTendencias();
    });
    $("seg-rango").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      estado.horas = Number(b.dataset.horas);
      $("seg-rango").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      cargarTendencias();
    });
  }

  function irATendencia(tag) {
    if (!estado.seleccion.includes(tag)) {
      estado.seleccion.unshift(tag);
      if (estado.seleccion.length > MAX_SENSORES) estado.seleccion.pop();
    }
    irA("tendencias");
  }

  function pintarChips() {
    $("chips-sensores").replaceChildren(...estado.seleccion.map((tag) => {
      const s = estado.porTag[tag] || { nombre: tag };
      return el("span", { clase: "chip-sel" }, s.nombre,
        el("button", { type: "button", "aria-label": "Quitar " + s.nombre, texto: "×",
                       onclick: () => { estado.seleccion = estado.seleccion.filter((t) => t !== tag); cargarTendencias(); } }));
    }));
  }

  async function cargarTendencias() {
    pintarChips();
    estado.graficos.forEach((g) => g.dispose());
    estado.graficos = [];
    const cont = $("graficos");
    if (!estado.ultima) await actualizarCabecera();
    if (!estado.ultima) { vacio(cont, "No hay lecturas para esta fuente."); $("graf-estado-tend").replaceChildren(); return; }
    if (!estado.seleccion.length) { vacio(cont, "Agregue al menos un sensor para ver su tendencia."); return; }
    const hasta = new Date(estado.ultima);
    const desde = new Date(hasta.getTime() - estado.horas * 3600e3);
    const paso = PASO_POR_HORAS[estado.horas];
    $("tend-periodo").textContent = `Del ${fechaHora(desde)} al ${fechaHora(hasta)}, promedio cada ${paso.replace("min", " min").replace("h", " hora")}`;
    let serie, hist;
    try {
      [serie, hist] = await Promise.all([
        api("/lecturas/serie", { params: { tags: estado.seleccion.join(","), desde: desde.toISOString(), hasta: hasta.toISOString(), paso, fuente: estado.fuente } }),
        api("/estado/historial", { params: { fuente: estado.fuente, desde: desde.toISOString(), hasta: hasta.toISOString() } }),
      ]);
    } catch (e) { mostrarError(cont, e); return; }

    const gEstado = graficoEstado($("graf-estado-tend"), hist, desde, hasta, { left: 54, right: 16 });
    if (gEstado) estado.graficos.push(gEstado);

    const bloques = serie.series.map((s) => {
      const info = estado.porTag[s.tag] || { nombre: s.tag };
      const nodo = el("div", { clase: "grafico", role: "img", "aria-label": `Tendencia de ${info.nombre}` });
      const titulo = el("div", { clase: "grafico-titulo" },
        el("span", {}, el("strong", { texto: info.nombre }), " ", el("span", { clase: "tenue", texto: `(${s.unidad})` })),
        el("span", { clase: "tenue", texto: rangoTexto(info) || "Sin rango normal definido" }));
      return { s, info, nodo, wrap: el("div", {}, titulo, s.puntos.length ? nodo : el("div", { clase: "vacio", texto: "Sin lecturas en este periodo." })) };
    });
    cont.replaceChildren(...bloques.map((b) => b.wrap));
    bloques.filter((b) => b.s.puntos.length).forEach((b) => estado.graficos.push(graficoLinea(b.nodo, b.s, b.info, desde, hasta)));
    echarts.connect(estado.graficos);
  }

  function graficoLinea(nodo, s, info, desde, hasta) {
    const t = s.puntos.map((p) => new Date(p.t).getTime());
    const prom = s.puntos.map((p, i) => [t[i], p.prom]);
    const minimo = s.puntos.map((p, i) => [t[i], p.min]);
    const ancho = s.puntos.map((p, i) => [t[i], p.max - p.min]);
    const conRango = info.normal_min !== null && info.normal_min !== undefined && info.normal_max !== null && info.normal_max !== undefined;
    const g = echarts.init(nodo, null, { renderer: "canvas" });
    g.setOption({
      animation: false,
      grid: { left: 54, right: 16, top: 12, bottom: 28 },
      xAxis: { type: "time", min: desde.getTime(), max: hasta.getTime(),
               axisLabel: { color: C.tenue, hideOverlap: true, showMinLabel: false, showMaxLabel: false, formatter: (v) => fmtDiaHora.format(new Date(v)) },
               axisLine: { lineStyle: { color: C.eje } }, splitLine: { show: false } },
      yAxis: { type: "value", scale: true, axisLabel: { color: C.tenue }, splitLine: { lineStyle: { color: C.grilla } },
               // el eje siempre incluye el rango normal, para ver de inmediato si la serie está dentro o fuera
               min: conRango ? (v) => Math.floor(Math.min(v.min, Number(info.normal_min))) : null,
               max: conRango ? (v) => Math.ceil(Math.max(v.max, Number(info.normal_max))) : null },
      tooltip: { trigger: "axis", backgroundColor: "#232b3d", borderColor: "#2e3646", textStyle: { color: C.texto },
        axisPointer: { type: "line", lineStyle: { color: C.tenue } },
        formatter: (ps) => {
          const i = ps[0].dataIndex; const p = s.puntos[i];
          return `${fmtDiaHora.format(new Date(p.t))}<br><b>${numero(p.prom)} ${s.unidad}</b> promedio<br>` +
                 `<span style="color:${C.texto2}">mín ${numero(p.min)}, máx ${numero(p.max)}</span>`;
        } },
      series: [
        { name: "mín", type: "line", data: minimo, stack: "banda", symbol: "none", lineStyle: { opacity: 0 }, silent: true },
        { name: "rango", type: "line", data: ancho, stack: "banda", symbol: "none", lineStyle: { opacity: 0 },
          areaStyle: { color: C.banda }, silent: true },
        { name: info.nombre, type: "line", data: prom, symbol: "none", lineStyle: { width: 2, color: C.serie }, itemStyle: { color: C.serie },
          markArea: conRango ? { silent: true, itemStyle: { color: C.normal, borderColor: C.normalBorde, borderWidth: 1, borderType: "dashed" },
            label: { show: true, position: "insideTopRight", color: C.tenue, fontSize: 11, formatter: "Rango normal" },
            data: [[{ yAxis: Number(info.normal_min) }, { yAxis: Number(info.normal_max) }]] } : undefined },
      ],
    });
    return g;
  }

  // ------------------------------------------------------------ ALARMAS
  function configurarAlarmas() {
    $("seg-alarmas").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      estado.alarmasActivas = b.dataset.activas === "true";
      $("seg-alarmas").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      cargarAlarmas();
    });
  }

  async function cargarAlarmas() {
    const cont = $("tabla-alarmas");
    let lista;
    try { lista = await api("/alarmas", { params: { activas: estado.alarmasActivas, fuente: estado.fuente } }); }
    catch (e) { mostrarError(cont, e); return; }
    if (!lista.length) {
      vacio(cont, estado.alarmasActivas ? "No hay alarmas activas." : "No hay alarmas registradas para esta fuente.");
      return;
    }
    const SEV = { critica: "Crítica", advertencia: "Advertencia", aviso: "Aviso" };
    const ORIGEN = { setpoint: "Límite", regla: "Regla", modelo: "Modelo" };
    const filas = lista.map((a) => {
      let estadoCelda;
      if (a.reconocida_en) {
        estadoCelda = el("div", {}, el("div", { texto: `Reconocida por ${a.reconocida_por || "—"}` }),
          el("div", { clase: "tenue", texto: fechaHora(a.reconocida_en) }),
          a.comentario ? el("div", { texto: "“" + a.comentario + "”" }) : null);
      } else if (puede(2)) {
        estadoCelda = el("button", { clase: "btn btn-chico", type: "button", texto: "Reconocer", onclick: () => reconocer(a) });
      } else {
        estadoCelda = el("span", { clase: "tenue", texto: "Sin reconocer" });
      }
      return el("tr", {},
        el("td", {}, el("span", { clase: "sev " + a.severidad, texto: SEV[a.severidad] || a.severidad })),
        el("td", { clase: "tab", texto: fechaHora(a.inicio) }),
        el("td", {}, el("div", { texto: a.mensaje || "—" }), a.accion ? el("div", { clase: "tenue", texto: a.accion }) : null,
           a.fin ? el("div", { clase: "tenue", texto: "Cerrada " + fechaHora(a.fin) }) : null),
        el("td", { texto: a.sensor ? (estado.porTag[a.sensor] || { nombre: a.sensor }).nombre : "—" }),
        el("td", { texto: ORIGEN[a.origen] || a.origen }),
        el("td", {}, estadoCelda));
    });
    cont.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {}, ["Severidad", "Inicio", "Alarma y acción recomendada", "Sensor", "Origen", "Estado"].map((t) => el("th", { texto: t })))),
      el("tbody", {}, filas)));
  }

  function reconocer(alarma) {
    const dlg = $("dlg-reconocer");
    $("dlg-reconocer-texto").textContent = `${alarma.mensaje || "Alarma"}, iniciada el ${fechaHora(alarma.inicio)}.`;
    $("dlg-comentario").value = "";
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok") return;
      try {
        await api(`/alarmas/${alarma.id}/reconocer`, { metodo: "POST", cuerpo: { comentario: $("dlg-comentario").value.trim() || null } });
        toast("Alarma reconocida");
        cargarAlarmas(); actualizarCabecera();
      } catch (e) { toast(e.message, "error"); }
    };
    dlg.showModal();
  }

  // ------------------------------------------------------------ MANTENIMIENTO
  function configurarMantenimiento() {
    $("form-mant").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const msg = $("msg-mant");
      const cuerpo = {
        componente: $("m-componente").value.trim(),
        tipo: $("m-tipo").value,
        tipo_falla: $("m-falla").value || null,
        fecha_inicio: isoLocal($("m-inicio").value),
        fecha_fin: isoLocal($("m-fin").value),
        descripcion: $("m-desc").value.trim() || null,
      };
      if (!cuerpo.componente || !cuerpo.fecha_inicio) { msg.className = "mensaje error"; msg.textContent = "Indique el componente y la fecha de inicio."; return; }
      try {
        await api("/mantenimientos", { metodo: "POST", cuerpo });
        ev.target.reset();
        msg.className = ""; msg.textContent = "";
        toast("Mantenimiento registrado");
        cargarMantenimiento();
      } catch (e) { msg.className = "mensaje error"; msg.textContent = e.message; }
    });
  }

  async function cargarMantenimiento() {
    const cont = $("tabla-mant");
    let lista;
    try { lista = await api("/mantenimientos"); } catch (e) { mostrarError(cont, e); return; }
    if (!lista.length) { vacio(cont, puede(3) ? "Aún no hay mantenimientos. Registre el primero en el formulario de arriba." : "Aún no hay mantenimientos registrados."); return; }
    const TIPO = { correctivo: "Correctivo", preventivo: "Preventivo", predictivo: "Predictivo" };
    const titulo = (cod) => (estado.tiposFalla.find((f) => f.codigo === cod) || { titulo: cod }).titulo;
    cont.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {}, ["Inicio", "Término", "Componente", "Tipo", "Falla", "Descripción", "Registrado por"].map((t) => el("th", { texto: t })))),
      el("tbody", {}, lista.map((m) => el("tr", {},
        el("td", { clase: "tab", texto: fechaHora(m.fecha_inicio) }),
        el("td", { clase: "tab", texto: m.fecha_fin ? fechaHora(m.fecha_fin) : "En curso" }),
        el("td", { texto: m.componente }),
        el("td", { texto: TIPO[m.tipo] || m.tipo }),
        el("td", { texto: m.falla ? titulo(m.falla) : "—" }),
        el("td", { texto: m.descripcion || "—" }),
        el("td", { texto: m.registrado_por }))))));
  }

  // ------------------------------------------------------------ USUARIOS (administrador)
  function configurarUsuarios() {
    $("form-usuario").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const msg = $("msg-usuario");
      const cuerpo = { nombre: $("u-nombre").value.trim(), email: $("u-email").value.trim(), rol: $("u-rol").value, clave_temporal: $("u-clave").value };
      try {
        await api("/usuarios", { metodo: "POST", cuerpo });
        ev.target.reset();
        msg.className = ""; msg.textContent = "";
        toast(`Usuario creado. Entréguele su contraseña temporal a ${cuerpo.nombre}.`);
        cargarUsuarios();
      } catch (e) { msg.className = "mensaje error"; msg.textContent = e.message; }
    });
  }

  async function cargarUsuarios() {
    if (!puede(4)) return;
    const cont = $("tabla-usuarios");
    let lista, aud;
    try { [lista, aud] = await Promise.all([api("/usuarios"), api("/usuarios/auditoria", { params: { limite: 50 } })]); }
    catch (e) { mostrarError(cont, e); return; }
    const ahora = Date.now();
    cont.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {}, ["Nombre", "Correo", "Rol", "Estado", "Último acceso", "Acciones"].map((t) => el("th", { texto: t })))),
      el("tbody", {}, lista.map((u) => {
        const yo = u.id === estado.usuario.id;
        const selRol = el("select", { clase: "compacto", "aria-label": "Rol de " + u.nombre, disabled: yo },
          Object.entries(ROLES).map(([v, t]) => el("option", { value: v, selected: v === u.rol, texto: t })));
        selRol.addEventListener("change", () => modificarUsuario(u, { rol: selRol.value }));
        const bloqueado = u.bloqueado_hasta && new Date(u.bloqueado_hasta).getTime() > ahora;
        const estadoTxt = !u.activo ? "Inactivo" : bloqueado ? `Bloqueado hasta ${fmtHora.format(new Date(u.bloqueado_hasta))}` : u.debe_cambiar_clave ? "Debe cambiar contraseña" : "Activo";
        return el("tr", {},
          el("td", { texto: u.nombre + (yo ? " (usted)" : "") }),
          el("td", { texto: u.email }),
          el("td", {}, selRol),
          el("td", { texto: estadoTxt }),
          el("td", { clase: "tab", texto: u.ultimo_acceso ? fechaHora(u.ultimo_acceso) : "Nunca" }),
          el("td", {}, el("div", { clase: "acciones" },
            yo ? null : el("button", { clase: "btn btn-chico", type: "button", texto: u.activo ? "Desactivar" : "Activar",
                                     onclick: () => modificarUsuario(u, { activo: !u.activo }) }),
            el("button", { clase: "btn btn-chico", type: "button", texto: "Contraseña temporal", onclick: () => claveTemporal(u) }))));
      }))));
    const ca = $("tabla-auditoria");
    if (!aud.length) { vacio(ca, "Sin registros."); return; }
    ca.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {}, ["Fecha", "Correo", "Evento", "IP", "Detalle"].map((t) => el("th", { texto: t })))),
      el("tbody", {}, aud.map((a) => el("tr", {},
        el("td", { clase: "tab", texto: fechaHora(a.fecha) }),
        el("td", { texto: a.email || "—" }),
        el("td", { texto: ACCIONES_AUD[a.accion] || a.accion }),
        el("td", { clase: "tab", texto: a.ip || "—" }),
        el("td", { clase: "tenue", texto: a.detalle || "" }))))));
  }

  async function modificarUsuario(u, cambios) {
    try {
      await api(`/usuarios/${u.id}`, { metodo: "PATCH", cuerpo: cambios });
      toast(`${u.nombre}: cambios guardados`);
    } catch (e) { toast(e.message, "error"); }
    cargarUsuarios();
  }

  function claveTemporal(u) {
    const dlg = $("dlg-clave");
    $("dlg-clave-texto").textContent = `${u.nombre} deberá cambiarla en su próximo ingreso. Si su cuenta estaba bloqueada, queda desbloqueada.`;
    $("dlg-clave-valor").value = "";
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok") return;
      try {
        await api(`/usuarios/${u.id}/restablecer-clave`, { metodo: "POST", cuerpo: { clave_temporal: $("dlg-clave-valor").value } });
        toast(`Contraseña temporal asignada a ${u.nombre}`);
        cargarUsuarios();
      } catch (e) { toast(e.message, "error"); }
    };
    dlg.showModal();
  }

  // ------------------------------------------------------------ TIEMPO REAL (Canal WebSocket y AWS IoT Core)
  let clienteMqtt = null;
  let reintentoMqttTimer = null;
  let wsLocal = null;

  function actualizarBadgeTiempoReal(conectado, textoExtra = "") {
    const b = $("cab-tiempo-real");
    if (!b) return;
    if (conectado) {
      b.className = "chip en-vivo";
      b.replaceChildren(el("span", { clase: "punto" }), "En vivo (MQTT)");
      b.title = "Canal de telemetría en tiempo real activo." + (textoExtra ? " " + textoExtra : "");
    } else {
      b.className = "chip offline";
      b.replaceChildren(el("span", { clase: "punto" }), "Polling (60s)");
      b.title = "Modo actualización periódica cada 60s." + (textoExtra ? " " + textoExtra : "");
    }
  }

  function conectarCanalTiempoReal() {
    clearTimeout(reintentoMqttTimer);
    actualizarBadgeTiempoReal(false, "Conectando...");

    // 1. Canal WebSocket en vivo
    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${location.host}/api/ws/telemetria`;

    try {
      wsLocal = new WebSocket(wsUrl);
      wsLocal.onopen = () => {
        console.info("Canal en vivo WebSocket conectado:", wsUrl);
        actualizarBadgeTiempoReal(true);
      };
      wsLocal.onmessage = (ev) => {
        try {
          const datos = JSON.parse(ev.data);
          const topic = datos.topic || "planta/asfalto/molino/telemetria";
          procesarEventoMqtt(topic, datos);
        } catch (e) {
          console.error("Error procesando mensaje WebSocket:", e);
        }
      };
      wsLocal.onclose = () => {
        actualizarBadgeTiempoReal(false, "Reconectando...");
        reintentoMqttTimer = setTimeout(conectarCanalTiempoReal, 5000);
      };
      wsLocal.onerror = () => {
        actualizarBadgeTiempoReal(false);
      };
    } catch (e) {
      actualizarBadgeTiempoReal(false);
    }

    // 2. Intentar también conexión MQTT AWS IoT Core directa si Paho está disponible
    conectarMqttAwsIot();
  }

  async function conectarMqttAwsIot() {
    try {
      if (!window.Paho || !window.Paho.MQTT) return;
      const cfg = await api("/iot/ws-url");
      if (!cfg || !cfg.disponible || !cfg.url) return;

      const urlObj = new URL(cfg.url);
      const host = urlObj.hostname;
      const path = urlObj.pathname + urlObj.search;
      const clientId = "qla_dash_" + Math.random().toString(16).slice(2, 10);
      const client = new Paho.MQTT.Client(host, 443, path, clientId);

      client.onMessageArrived = (msg) => {
        try {
          const payload = JSON.parse(msg.payloadString);
          procesarEventoMqtt(msg.destinationName, payload);
        } catch (e) {}
      };

      client.connect({
        useSSL: true,
        timeout: 8,
        keepAliveInterval: 30,
        onSuccess: () => {
          console.info("Conectado exitosamente a AWS IoT Core por WebSocket");
          actualizarBadgeTiempoReal(true);
          if (cfg.topics && cfg.topics.telemetria) client.subscribe(cfg.topics.telemetria);
          if (cfg.topics && cfg.topics.predicciones) client.subscribe(cfg.topics.predicciones);
        },
        onFailure: (err) => {
          console.info("AWS IoT Core WebSocket no disponible directamente:", err.errorMessage);
        }
      });
      clienteMqtt = client;
    } catch (e) {}
  }

  function procesarEventoMqtt(topic, payload) {
    if (topic.endsWith("/telemetria")) {
      const lectura = payload.lectura_actual || payload;
      const ts = payload.timestamp ? new Date(payload.timestamp * 1000) : new Date();
      estado.ultima = ts.toISOString();
      $("cab-lectura").textContent = "Última lectura " + fechaHora(estado.ultima);
      $("ind-hora").textContent = fmtHora.format(ts);
      $("ind-fecha").textContent = fechaHora(estado.ultima).split(",")[0] + " (en vivo)";
      if (lectura.ESTADO_operacion) {
        const est = ESTADOS[lectura.ESTADO_operacion.toLowerCase()] || { texto: lectura.ESTADO_operacion, color: "#199e70" };
        const chip = $("cab-estado");
        if (chip) chip.replaceChildren(el("span", { clase: "punto", style: `background:${est.color}` }), est.texto);
        const indEstado = $("ind-estado");
        if (indEstado) indEstado.textContent = est.texto;
      }
      if (estado.lecturasActuales) {
        let fueras = 0;
        estado.lecturasActuales.forEach((l) => {
          if (l.tag in lectura) {
            l.valor = lectura[l.tag];
            l.ts = estado.ultima;
            l.fuera_de_rango = (l.normal_min !== null && l.valor < l.normal_min) || (l.normal_max !== null && l.valor > l.normal_max);
          }
          if (l.fuera_de_rango) fueras++;
        });
        $("ind-fuera").textContent = `${fueras} de ${estado.lecturasActuales.length}`;
        $("ind-fuera-det").textContent = fueras ? "Revise las lecturas marcadas" : "Todas dentro de su rango";
        if (estado.vista === "panel") {
          pintarInstrumentos(estado.lecturasActuales);
        }
      }
    } else if (topic.endsWith("/predicciones")) {
      if (payload.alerta_activa) {
        toast(`⚠️ Alerta predictiva: Posible falla ${payload.falla || 'detectada'} (Riesgo 24h: ${((payload.riesgo_24h || 0) * 100).toFixed(1)}%)`, "error");
      }
      if (estado.prediccionesActuales && payload.riesgo_24h !== undefined) {
        const p24 = estado.prediccionesActuales.find(p => p.horizonte === "24h");
        if (p24) {
          p24.prob_falla = payload.riesgo_24h;
          p24.falla = payload.falla;
          p24.titulo = payload.falla;
          p24.ts = new Date().toISOString();
        }
        if (estado.vista === "panel") {
          pintarPredicciones(estado.prediccionesActuales);
        }
      }
    }
  }

  iniciar();
})();
