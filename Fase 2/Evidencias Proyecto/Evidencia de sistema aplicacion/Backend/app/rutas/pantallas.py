"""Un endpoint por pantalla del dashboard (diseño e historias de usuario HU-01 a HU-16).

El "ahora" de cada pantalla es el último minuto con datos de la fuente elegida (simulado o real),
no la hora del reloj: así la reproducción de la simulación se ve igual que la operación real.
"""
import datetime as dt
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config
from ..db import cursor
from ..seguridad import OPERADOR, requiere_nivel

router = APIRouter(tags=["Pantallas del dashboard"])
lector = requiere_nivel(OPERADOR)
Fuente = Literal["simulado", "real"]

EN_MARCHA = ("produccion", "limpieza")
TEXTO_ESTADO = {"produccion": "En producción", "limpieza": "Limpieza de línea", "detenida": "Planta detenida",
                "preparacion": "En preparación", "espera": "En espera", "mantenimiento": "En mantenimiento",
                "falla": "En falla"}
PRIORIDAD = {"critica": "alta", "advertencia": "media", "aviso": "baja"}
ORDEN_PRIORIDAD = {"alta": 0, "media": 1, "baja": 2}
FALLAS_FRECUENTES = ("Sobrecarga_Motor_Por_Asfalto_Frio", "Filtro_Obstruido", "Advertencia_Radar_Sucio_Betun")
HORIZONTES = ("24h", "5d", "15d")

# Equipo que se interviene por cada falla. 'bitacora' es el nombre del equipo en la bitácora de la
# planta y 'preventiva' el texto con que aparece en las mantenciones mensuales (igual que el Modelo 3).
EQUIPOS = [
    {"clave": "filtro", "equipo": "F-101 filtro de línea", "falla": "Filtro_Obstruido",
     "preventiva": "limpieza de filtro"},
    {"clave": "radar", "equipo": "TK-101 radar de nivel", "falla": "Advertencia_Radar_Sucio_Betun",
     "preventiva": "antena del radar"},
    {"clave": "caldera", "equipo": "TK-101 caldera / calefactor de betún",
     "falla": "Sobrecarga_Motor_Por_Asfalto_Frio", "preventiva": "mantención de caldera"},
    {"clave": "intercambiador", "equipo": "E-301 intercambiador de calor", "falla": "Ensuciamiento_Intercambiador",
     "preventiva": "intercambiador"},
    {"clave": "caudalimetro", "equipo": "FT-201 caudalímetro solución",
     "falla": "Cortocircuito_Transmisor_Caudal_Sol", "preventiva": "transmisor de caudal"},
    {"clave": "pt100", "equipo": "TT-101 Pt100 betún", "falla": "Falla_Electrica_PT100_Betun",
     "preventiva": "borneras"},
    {"clave": "rodamientos", "equipo": "MC-01 rodamientos del molino", "falla": "Desgaste_Rodamientos_Molino",
     "preventiva": "cambio preventivo de rodamientos"},
]

# Indicadores del día (mismos supuestos que el dashboard simulado de Franco)
CAUDAL_20MA = {"betun": 200.0, "solucion": 120.0}     # L/min a 20 mA de cada Coriolis
RELACION_OBJETIVO = (60.0, 68.0)
VOLTAJE_MOTOR_V, FACTOR_POTENCIA = 380.0, 0.85


def _sin_demo():
    if config.MODO_DEMO:
        raise HTTPException(409, "Esta pantalla necesita la base de datos (no disponible en modo demostración)")


def _equipo(cur, codigo: str) -> int:
    cur.execute("SELECT id FROM mantpred.equipos WHERE codigo = %s", (codigo,))
    f = cur.fetchone()
    if f is None:
        raise HTTPException(404, f"No existe el equipo {codigo}")
    return f["id"]


def _ahora(cur, eq: int, fuente: str) -> dict | None:
    """Último minuto con datos: instante, modo de operación y tipo de asfalto."""
    cur.execute("""SELECT ts, estado, tipo_asfalto FROM mantpred.estados_equipo
                   WHERE equipo_id = %s AND fuente = %s ORDER BY ts DESC LIMIT 1""", (eq, fuente))
    return cur.fetchone()


def _num(v):
    if v is None:
        return None
    f = float(v)
    return f if math.isfinite(f) else None


# =====================================================================
# PROCESO (HU-01, 02, 03, 05, 06, 07, 09, 15)
# =====================================================================
@router.get("/proceso", summary="Pantalla Proceso: estado general, medidores, diagnóstico, alarmas e indicadores")
def proceso(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado", u: dict = Depends(lector)):
    _sin_demo()
    with cursor() as cur:
        eq = _equipo(cur, equipo)
        ahora = _ahora(cur, eq, fuente)
        if ahora is None:
            return {"ts": None, "mensaje": "Sin datos para esta fuente"}
        ts, estado, tipo = ahora["ts"], ahora["estado"], ahora["tipo_asfalto"]
        en_marcha = estado in EN_MARCHA

        # Medidores: último valor de cada sensor con la banda normal del modo actual
        cur.execute(
            """SELECT s.tag, s.nombre, s.componente, s.variable, s.unidad, s.rango_min, s.rango_max,
                      coalesce(r.normal_min, s.normal_min) AS normal_min,
                      coalesce(r.normal_max, s.normal_max) AS normal_max,
                      l.ts, l.valor
               FROM mantpred.sensores s
               JOIN LATERAL (SELECT max(ts) AS ts FROM mantpred.lecturas
                             WHERE sensor_id = s.id AND fuente = %s AND ts <= %s) m ON TRUE
               JOIN mantpred.lecturas l ON l.sensor_id = s.id AND l.fuente = %s AND l.ts = m.ts
               LEFT JOIN mantpred.rangos_operacion r
                      ON r.sensor_id = s.id AND r.estado = %s AND r.tipo_asfalto = %s
               WHERE s.equipo_id = %s AND s.activo AND s.origen = 'simulado'
               ORDER BY s.componente, s.tag""",
            (fuente, ts, fuente, estado, tipo, eq))
        sensores = cur.fetchall()

        # Diagnóstico y vigilancia del último minuto en marcha (máximo 5 minutos de antigüedad)
        cur.execute(
            """SELECT p.modelo, p.ts, p.prob_falla, p.alerta, p.umbral, p.error_ae, p.indice_salud, p.detalle,
                      tf.codigo, tf.titulo, tf.accion, tf.prioridad
               FROM mantpred.predicciones p LEFT JOIN mantpred.tipos_falla tf ON tf.id = p.tipo_falla_id
               WHERE p.equipo_id = %s AND p.fuente = %s AND p.modelo IN ('diagnostico', 'autoencoder')
                 AND p.ts BETWEEN %s AND %s
               ORDER BY p.ts DESC LIMIT 2""",
            (eq, fuente, ts - dt.timedelta(minutes=5), ts))
        tiempo_real = {}
        for f in cur.fetchall():
            tiempo_real.setdefault(f["modelo"], f)
        diag, ae = tiempo_real.get("diagnostico"), tiempo_real.get("autoencoder")

        senalados = set()
        vigilancia = None
        if ae:
            sens = (ae["detalle"] or {}).get("sensores", [])
            if ae["alerta"]:
                senalados = {s["tag"] for s in sens}
            vigilancia = {"ts": ae["ts"], "error": _num(ae["error_ae"]), "umbral": _num(ae["umbral"]),
                          "alerta": ae["alerta"], "indice_salud": _num(ae["indice_salud"]), "sensores": sens}
        for s in sensores:
            lo, hi, v = _num(s["normal_min"]), _num(s["normal_max"]), _num(s["valor"])
            s["fuera_de_rango"] = v is not None and ((lo is not None and v < lo) or (hi is not None and v > hi))
            s["senalado_ae"] = s["tag"] in senalados

        diagnostico = None
        if diag:
            diagnostico = {"ts": diag["ts"], "falla": diag["codigo"], "titulo": diag["titulo"] or "Normal",
                           "accion": diag["accion"], "prioridad": diag["prioridad"],
                           "probabilidad_anomalia": _num(diag["prob_falla"]),
                           "confirmado_por_autoencoder": bool(diag["codigo"] and ae and ae["alerta"])}

        alarmas = _alarmas(cur, eq, fuente, True, 50, ts)
        panel = _panel_principal(estado, tipo, en_marcha, alarmas, diagnostico, vigilancia)
        riesgo = _riesgo_resumen(cur, eq, fuente, ts)
        indicadores = _indicadores_dia(cur, eq, fuente, ts, estado)

    return {"ts": ts, "fuente": fuente, "estado": estado, "estado_texto": TEXTO_ESTADO.get(estado, estado),
            "tipo_asfalto": tipo, "en_marcha": en_marcha, "panel": panel, "sensores": sensores,
            "diagnostico": diagnostico, "vigilancia": vigilancia, "alarmas_activas": alarmas,
            "riesgo": riesgo, "indicadores": indicadores,
            "modelos_aplican": en_marcha}


def _panel_principal(estado, tipo, en_marcha, alarmas, diagnostico, vigilancia) -> dict:
    """HU-01: estado general en una frase, con color y texto (nunca solo color)."""
    if alarmas:
        a = alarmas[0]
        color = "morado" if a.get("falla") == "Anomalia_Desconocida" else (
            "rojo" if a["prioridad"] == "alta" else "naranja")
        return {"nivel": "alarma", "color": color, "titulo": a["mensaje"], "accion": a["accion"],
                "origen": a["origen_texto"], "desde": a["inicio"]}
    if not en_marcha:
        return {"nivel": "informativo", "color": "gris", "titulo": TEXTO_ESTADO.get(estado, estado),
                "accion": "Los modelos se aplican con el molino en marcha.", "origen": None, "desde": None}
    if vigilancia and vigilancia["alerta"]:
        return {"nivel": "aviso", "color": "morado", "titulo": "Aviso de degradación",
                "accion": "El molino se aleja de su comportamiento sano. Revisar los sensores señalados.",
                "origen": "autoencoder", "desde": vigilancia["ts"]}
    return {"nivel": "normal", "color": "verde", "titulo": "Operación normal",
            "accion": None, "origen": "diagnóstico y vigilancia", "desde": None}


def _riesgo_resumen(cur, eq, fuente, ts) -> list:
    """Para cada falla, el horizonte más cercano con alerta (24h antes que 5d antes que 15d)."""
    filas = _prediccion_actual(cur, eq, fuente, ts)
    res = []
    for f in filas:
        nivel = next((hz for hz in HORIZONTES if f["horizontes"].get(hz, {}).get("alerta")), None)
        res.append({"falla": f["falla"], "titulo": f["titulo"], "riesgo_en": nivel})
    return res


def _indicadores_dia(cur, eq, fuente, ts, estado) -> dict:
    """HU-15: producción, relación betún/solución, marcha sin anomalía y energía del día de planta."""
    cur.execute("SELECT (date_trunc('day', %s AT TIME ZONE %s) AT TIME ZONE %s) AS inicio",
                (ts, config.ZONA_HORARIA, config.ZONA_HORARIA))
    inicio = cur.fetchone()["inicio"]
    cur.execute(
        """WITH s AS (SELECT tag, id FROM mantpred.sensores
                      WHERE tag IN ('CAU_bomba_lpm', 'AMP_vfd_motor_molino')),
                m AS (SELECT ts, estado FROM mantpred.estados_equipo
                      WHERE equipo_id = %s AND fuente = %s AND ts BETWEEN %s AND %s),
                c AS (SELECT DISTINCT ts FROM mantpred.condiciones_minuto
                      WHERE equipo_id = %s AND fuente = %s AND origen = 'modelo' AND ts BETWEEN %s AND %s)
           SELECT count(*) FILTER (WHERE m.estado IN ('produccion', 'limpieza')) AS min_marcha,
                  count(*) FILTER (WHERE m.estado IN ('produccion', 'limpieza') AND c.ts IS NULL) AS min_normal,
                  coalesce(sum(lc.valor) FILTER (WHERE m.estado = 'produccion'), 0) AS litros,
                  coalesce(sum(la.valor) FILTER (WHERE m.estado IN ('produccion', 'limpieza')), 0) AS amp_min
           FROM m
           LEFT JOIN c ON c.ts = m.ts
           LEFT JOIN mantpred.lecturas lc ON lc.ts = m.ts AND lc.fuente = %s
                                         AND lc.sensor_id = (SELECT id FROM s WHERE tag = 'CAU_bomba_lpm')
           LEFT JOIN mantpred.lecturas la ON la.ts = m.ts AND la.fuente = %s
                                         AND la.sensor_id = (SELECT id FROM s WHERE tag = 'AMP_vfd_motor_molino')""",
        (eq, fuente, inicio, ts, eq, fuente, inicio, ts, fuente, fuente))
        # (los parámetros repetidos son los mismos del día y la fuente)
    d = cur.fetchone()
    cur.execute(
        """SELECT s.tag, l.valor FROM mantpred.sensores s
           JOIN mantpred.lecturas l ON l.sensor_id = s.id AND l.fuente = %s AND l.ts = %s
           WHERE s.tag IN ('AMP_cau_betum_in', 'AMP_cau_solucion_in')""", (fuente, ts))
    lazo = {f["tag"]: float(f["valor"]) for f in cur.fetchall()}
    relacion = None
    if estado == "produccion" and "AMP_cau_betum_in" in lazo and "AMP_cau_solucion_in" in lazo \
            and lazo["AMP_cau_solucion_in"] < 20:
        qb = max(0.0, (lazo["AMP_cau_betum_in"] - 4) / 16) * CAUDAL_20MA["betun"]
        qs = max(0.0, (lazo["AMP_cau_solucion_in"] - 4) / 16) * CAUDAL_20MA["solucion"]
        relacion = round(100 * qb / (qb + qs), 1) if qb + qs > 0 else None
    min_marcha = d["min_marcha"]
    return {
        "desde": inicio,
        "produccion_t": round(float(d["litros"]) / 1000, 2),
        "relacion_betun_pct": relacion,
        "relacion_objetivo": RELACION_OBJETIVO,
        "relacion_fuera": relacion is not None and not (RELACION_OBJETIVO[0] <= relacion <= RELACION_OBJETIVO[1]),
        "marcha_sin_anomalia_pct": round(100 * d["min_normal"] / min_marcha, 1) if min_marcha else None,
        "horas_marcha": round(min_marcha / 60, 2),
        "energia_kwh": round(math.sqrt(3) * VOLTAJE_MOTOR_V * float(d["amp_min"]) * FACTOR_POTENCIA / 1000 / 60, 1),
    }


# =====================================================================
# PREDICCIÓN (HU-12, 13, 14)
# =====================================================================
def _prediccion_actual(cur, eq, fuente, ts) -> list:
    cur.execute("""SELECT max(ts) AS h FROM mantpred.predicciones
                   WHERE equipo_id = %s AND fuente = %s AND modelo = 'predictivo' AND ts <= %s
                     AND ts > %s - interval '72 hours'""",
                (eq, fuente, ts, ts))
    h = cur.fetchone()["h"]       # una predicción de hace más de 72 h ya no representa el estado actual
    if h is None:
        return []
    cur.execute(
        """SELECT tf.codigo, tf.titulo, tf.accion, tf.componente, p.horizonte, p.prob_falla, p.umbral, p.alerta,
                  p.dias_estimados, p.metodo, p.ts
           FROM mantpred.predicciones p JOIN mantpred.tipos_falla tf ON tf.id = p.tipo_falla_id
           WHERE p.equipo_id = %s AND p.fuente = %s AND p.modelo = 'predictivo' AND p.ts = %s
           ORDER BY tf.id""", (eq, fuente, h))
    por_falla = {}
    for f in cur.fetchall():
        x = por_falla.setdefault(f["codigo"], {"falla": f["codigo"], "titulo": f["titulo"], "accion": f["accion"],
                                               "componente": f["componente"], "metodo": f["metodo"],
                                               "emitida": f["ts"], "horizontes": {}})
        x["horizontes"][f["horizonte"]] = {"probabilidad": _num(f["prob_falla"]), "umbral": _num(f["umbral"]),
                                           "alerta": f["alerta"], "dias_estimados": _num(f["dias_estimados"])}
    return list(por_falla.values())


def _ultima_intervencion(cur, eq, fuente, ts) -> dict:
    """Fecha de la última intervención (correctiva o preventiva) de cada equipo, según la bitácora."""
    res = {}
    for e in EQUIPOS:
        cur.execute(
            """SELECT max(fecha_inicio) AS ultima FROM mantpred.mantenimientos
               WHERE equipo_id = %s AND fuente = %s AND fecha_inicio <= %s
                 AND (componente = %s OR (tipo = 'preventivo' AND descripcion ILIKE %s))""",
            (eq, fuente, ts, e["equipo"], f"%{e['preventiva']}%"))
        res[e["falla"]] = cur.fetchone()["ultima"]
    return res


@router.get("/prediccion", summary="Pantalla Predicción: semáforo de riesgo por falla y horizonte")
def prediccion(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado", u: dict = Depends(lector)):
    _sin_demo()
    with cursor() as cur:
        eq = _equipo(cur, equipo)
        ahora = _ahora(cur, eq, fuente)
        if ahora is None:
            return {"ts": None, "emitida": None, "fallas": []}
        ts = ahora["ts"]
        filas = _prediccion_actual(cur, eq, fuente, ts)
        ultimas = _ultima_intervencion(cur, eq, fuente, ts)
    for f in filas:
        ult = ultimas.get(f["falla"])
        f["ultima_intervencion"] = ult
        f["dias_desde_intervencion"] = round((ts - ult).total_seconds() / 86400, 1) if ult else None
        f["frecuente"] = f["falla"] in FALLAS_FRECUENTES
        f["alto_en"] = [hz for hz in HORIZONTES if f["horizontes"].get(hz, {}).get("alerta")]
    return {"ts": ts, "emitida": filas[0]["emitida"] if filas else None, "fallas": filas}


@router.get("/prediccion/evolucion", summary="Evolución del riesgo de las fallas frecuentes (HU-14)")
def prediccion_evolucion(horizonte: Literal["24h", "5d", "15d"] = "5d", dias: int = Query(7, ge=1, le=30),
                         equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado",
                         u: dict = Depends(lector)):
    _sin_demo()
    with cursor() as cur:
        eq = _equipo(cur, equipo)
        ahora = _ahora(cur, eq, fuente)
        if ahora is None:
            return {"series": []}
        ts = ahora["ts"]
        cur.execute(
            """SELECT tf.codigo, tf.titulo, p.ts, p.prob_falla, p.umbral
               FROM mantpred.predicciones p JOIN mantpred.tipos_falla tf ON tf.id = p.tipo_falla_id
               WHERE p.equipo_id = %s AND p.fuente = %s AND p.modelo = 'predictivo' AND p.horizonte = %s
                 AND tf.codigo = ANY(%s) AND p.ts BETWEEN %s AND %s
               ORDER BY tf.id, p.ts""",
            (eq, fuente, horizonte, list(FALLAS_FRECUENTES), ts - dt.timedelta(days=dias), ts))
        series = {}
        for f in cur.fetchall():
            s = series.setdefault(f["codigo"], {"falla": f["codigo"], "titulo": f["titulo"], "umbral": None,
                                                "puntos": []})
            s["umbral"] = _num(f["umbral"])
            s["puntos"].append({"t": f["ts"], "probabilidad": _num(f["prob_falla"])})
    horas = max((len(s["puntos"]) for s in series.values()), default=0)
    return {"horizonte": horizonte, "series": list(series.values()),
            "mensaje": "Se necesitan al menos dos horas de historial" if horas < 2 else None}


# =====================================================================
# ALARMAS (HU-09, 10, 11)
# =====================================================================
def _alarmas(cur, eq, fuente, activas: bool, limite: int, ts) -> list:
    cur.execute(
        f"""SELECT a.id, a.inicio, a.fin, a.mensaje, a.severidad, a.origen, a.valor, a.detalle,
                   tf.codigo AS falla, tf.componente AS componente_falla,
                   coalesce(tf.accion, r.accion) AS accion, r.codigo AS regla, r.componente AS componente_regla
            FROM mantpred.alarmas a
            LEFT JOIN mantpred.tipos_falla tf ON tf.id = a.tipo_falla_id
            LEFT JOIN mantpred.reglas_alarma r ON r.id = a.regla_id
            WHERE a.equipo_id = %s AND a.fuente = %s AND a.inicio <= %s {"AND a.fin IS NULL" if activas else ""}
            ORDER BY a.inicio DESC LIMIT %s""", (eq, fuente, ts, limite))
    res = []
    for a in cur.fetchall():
        fin = a["fin"]
        prioridad = PRIORIDAD.get(a["severidad"], "media")
        origen_texto = (a["detalle"] or {}).get("origen") or ("regla fija" if a["origen"] == "regla" else "modelo")
        res.append({"id": a["id"], "inicio": a["inicio"], "fin": fin, "activa": fin is None,
                    "mensaje": a["mensaje"], "prioridad": prioridad,
                    "origen": "regla fija" if a["origen"] == "regla" else "modelo",
                    "origen_texto": origen_texto, "falla": a["falla"], "regla": a["regla"],
                    "componente": a["componente_falla"] or a["componente_regla"],
                    "accion": a["accion"], "valor": _num(a["valor"]),
                    "duracion_min": round(((fin or ts) - a["inicio"]).total_seconds() / 60)})
    if activas:
        res.sort(key=lambda x: (ORDEN_PRIORIDAD.get(x["prioridad"], 9), -x["inicio"].timestamp()))
    return res


@router.get("/alarmas/pantalla", summary="Pantalla Alarmas: activas e historial (solo consulta)")
def alarmas_pantalla(limite: int = Query(200, ge=1, le=500), equipo: str = config.EQUIPO_POR_DEFECTO,
                     fuente: Fuente = "simulado", u: dict = Depends(lector)):
    _sin_demo()
    with cursor() as cur:
        eq = _equipo(cur, equipo)
        ahora = _ahora(cur, eq, fuente)
        if ahora is None:
            return {"ts": None, "activas": [], "historial": []}
        ts = ahora["ts"]
        return {"ts": ts, "activas": _alarmas(cur, eq, fuente, True, 50, ts),
                "historial": _alarmas(cur, eq, fuente, False, limite, ts)}


# =====================================================================
# SALUD DEL EQUIPO (HU-08)
# =====================================================================
@router.get("/salud-equipo", summary="Pantalla Salud: error medio diario del autoencoder")
def salud_equipo(dias: int = Query(30, ge=1, le=120), equipo: str = config.EQUIPO_POR_DEFECTO,
                 fuente: Fuente = "simulado", u: dict = Depends(lector)):
    _sin_demo()
    with cursor() as cur:
        eq = _equipo(cur, equipo)
        ahora = _ahora(cur, eq, fuente)
        if ahora is None:
            return {"umbral": None, "dias": []}
        ts = ahora["ts"]
        desde = ts - dt.timedelta(days=dias)
        cur.execute(
            """WITH ae AS (SELECT (ts AT TIME ZONE %s)::date AS dia, error_ae, umbral
                           FROM mantpred.predicciones
                           WHERE equipo_id = %s AND fuente = %s AND modelo = 'autoencoder' AND ts BETWEEN %s AND %s),
                    cond AS (SELECT (ts AT TIME ZONE %s)::date AS dia, count(DISTINCT ts) AS minutos
                             FROM mantpred.condiciones_minuto
                             WHERE equipo_id = %s AND fuente = %s AND origen = 'modelo' AND ts BETWEEN %s AND %s
                             GROUP BY 1)
               SELECT ae.dia, avg(ae.error_ae) AS error_medio, count(*) AS minutos_marcha,
                      max(ae.umbral) AS umbral, coalesce(max(cond.minutos), 0) AS minutos_anomalia
               FROM ae LEFT JOIN cond ON cond.dia = ae.dia
               GROUP BY ae.dia ORDER BY ae.dia""",
            (config.ZONA_HORARIA, eq, fuente, desde, ts, config.ZONA_HORARIA, eq, fuente, desde, ts))
        filas = cur.fetchall()
    umbral = next((_num(f["umbral"]) for f in reversed(filas) if f["umbral"] is not None), None)
    dias_lista = [{"dia": f["dia"], "error_medio": _num(f["error_medio"]), "minutos_marcha": f["minutos_marcha"],
                   "minutos_anomalia": f["minutos_anomalia"],
                   "sobre_umbral": umbral is not None and f["error_medio"] is not None
                                   and float(f["error_medio"]) > umbral} for f in filas]
    return {"ts": ts, "umbral": umbral, "dias": dias_lista,
            "dias_sobre_umbral": sum(1 for d in dias_lista if d["sobre_umbral"])}


# =====================================================================
# MANTENIMIENTO (HU-13, 16)
# =====================================================================
@router.get("/mantenimiento/pantalla", summary="Pantalla Mantenimiento: estado por equipo y bitácora (solo lectura)")
def mantenimiento_pantalla(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado",
                           u: dict = Depends(lector)):
    _sin_demo()
    with cursor() as cur:
        eq = _equipo(cur, equipo)
        ahora = _ahora(cur, eq, fuente)
        ts = ahora["ts"] if ahora else dt.datetime.now(dt.timezone.utc)
        riesgo15 = {f["falla"]: f["horizontes"].get("15d", {}) for f in _prediccion_actual(cur, eq, fuente, ts)}
        filas = []
        for e in EQUIPOS:
            cur.execute(
                """SELECT fecha_inicio, tipo FROM mantpred.mantenimientos
                   WHERE equipo_id = %s AND fuente = %s AND fecha_inicio <= %s
                     AND (componente = %s OR (tipo = 'preventivo' AND descripcion ILIKE %s))
                   ORDER BY fecha_inicio""",
                (eq, fuente, ts, e["equipo"], f"%{e['preventiva']}%"))
            regs = cur.fetchall()
            corr = [r["fecha_inicio"] for r in regs if r["tipo"] == "correctivo"]
            difs = [(b - a).total_seconds() / 86400 for a, b in zip(corr, corr[1:])]
            ultima = regs[-1]["fecha_inicio"] if regs else None
            r15 = riesgo15.get(e["falla"], {})
            filas.append({"equipo": e["equipo"], "falla": e["falla"], "correctivas": len(corr),
                          "preventivas": sum(1 for r in regs if r["tipo"] == "preventivo"),
                          "mtbf_dias": round(sum(difs) / len(difs), 1) if difs else None,
                          "ultima_intervencion": ultima,
                          "dias_desde": round((ts - ultima).total_seconds() / 86400, 1) if ultima else None,
                          "riesgo_15d": r15.get("alerta"), "probabilidad_15d": r15.get("probabilidad")})
        cur.execute(
            """SELECT count(*) AS total, count(*) FILTER (WHERE tipo = 'preventivo') AS preventivas
               FROM mantpred.mantenimientos WHERE equipo_id = %s AND fuente = %s AND fecha_inicio <= %s""",
            (eq, fuente, ts))
        tot = cur.fetchone()
        cur.execute(
            """SELECT fecha_inicio, componente, tipo, descripcion FROM mantpred.mantenimientos
               WHERE equipo_id = %s AND fuente = %s AND fecha_inicio <= %s
               ORDER BY fecha_inicio DESC LIMIT 60""", (eq, fuente, ts))
        bitacora = cur.fetchall()
    return {"ts": ts, "equipos": filas,
            "pct_planificado": round(100 * tot["preventivas"] / tot["total"], 1) if tot["total"] else None,
            "total_intervenciones": tot["total"], "bitacora": bitacora,
            "nota": "La bitácora la mantiene la planta fuera del dashboard; aquí es solo de lectura."}
