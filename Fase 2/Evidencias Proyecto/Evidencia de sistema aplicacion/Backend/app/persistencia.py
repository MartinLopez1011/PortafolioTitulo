"""Guarda en PostgreSQL (Supabase) lo que produce la Lambda de inferencia.

Recibe el mismo registro que la Lambda guarda en DynamoDB:

    {"equipo_id": "MOLINO_QLA_01", "timestamp": 1790000000,
     "lectura": {31 variables + ESTADO_operacion + TIPO_asfalto},
     "diagnostico": {...}, "vigilancia": {...}, "predictivo": {"pronosticos": {...}},
     "estado_operacion": "Produccion"}

y escribe:
  * estados_equipo y lecturas: la primera lectura de cada minuto (el resto del minuto se descarta,
    así la base crece igual con lecturas cada 2 s o cada 1 min).
  * predicciones: diagnóstico y vigilancia una vez por minuto; predicción una vez por hora
    (se actualiza con el último cálculo de esa hora).
  * condiciones_minuto: qué condición anómala hubo en el minuto (modelo o regla fija).
  * alarmas: se activan si la condición aparece en 3 de los últimos 5 minutos con datos
    y se cierran cuando aparece en 1 o menos (HU-09).

No depende de FastAPI: se usa desde el endpoint de ingesta y desde la Lambda de persistencia.
Usa un cursor DB-API con parámetros %s (psycopg o pg8000).
"""
from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

ESTADOS = {"produccion": "produccion", "producción": "produccion", "limpieza": "limpieza",
           "detenida": "detenida", "detenido": "detenida", "preparacion": "preparacion",
           "preparación": "preparacion", "espera": "espera", "mantenimiento": "mantenimiento",
           "falla": "falla"}
TIPOS = {"convencional": "convencional", "plastomerico": "plastomerico", "plastomérico": "plastomerico",
         "ninguno": "ninguno"}
EN_MARCHA = {"produccion", "limpieza"}          # los modelos se aplican solo con el molino en marcha
HORIZONTES = {"24 h": "24h", "24h": "24h", "5 días": "5d", "5d": "5d", "15 días": "15d", "15d": "15d"}
PRIORIDAD_A_SEVERIDAD = {"alta": "critica", "media": "advertencia", "baja": "aviso"}

# HU-07: si el diagnóstico dice "normal" pero el autoencoder señala sensores de una falla rara,
# se indica esa falla rara; si no coincide con ninguna, es "comportamiento anómalo no clasificado".
SENSORES_FALLA_RARA = {
    "VIB_vel_motor_molino": "Desgaste_Rodamientos_Molino",
    "AMP_vib_motor_molino": "Desgaste_Rodamientos_Molino",
    "AMP_eco_betum_dep": "Advertencia_Radar_Sucio_Betun",
    "EST_niv_betum_dep": "Advertencia_Radar_Sucio_Betun",
    "PRE_intercambiador_bar": "Ensuciamiento_Intercambiador",
}
ANOMALIA_DESCONOCIDA = "Anomalia_Desconocida"
N_VARIABLES_AE = 31

_cache: dict[str, Any] = {}


# ---------------------------------------------------------------- utilidades
def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _instante(ts) -> dt.datetime:
    """Epoch (s o ms) o texto ISO -> datetime UTC."""
    if ts is None:
        return dt.datetime.now(dt.timezone.utc)
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.strip().replace(".", "", 1).isdigit()):
        v = float(ts)
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, dt.timezone.utc)
    t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _catalogos(cur) -> dict:
    """Ids de sensores, fallas, reglas y equipos. Se leen una vez por proceso."""
    if not _cache:
        cur.execute("SELECT id, tag FROM mantpred.sensores WHERE activo")
        _cache["sensores"] = {_get(r, "tag", 1): _get(r, "id", 0) for r in cur.fetchall()}
        cur.execute("SELECT id, codigo, prioridad, titulo FROM mantpred.tipos_falla")
        _cache["fallas"] = {_get(r, "codigo", 1): {"id": _get(r, "id", 0), "prioridad": _get(r, "prioridad", 2),
                                                    "titulo": _get(r, "titulo", 3)} for r in cur.fetchall()}
        cur.execute("""SELECT r.id, r.codigo, s.tag, r.comparacion, r.limite, r.tipo_asfalto, r.solo_en_marcha,
                              r.prioridad, r.mensaje
                       FROM mantpred.reglas_alarma r JOIN mantpred.sensores s ON s.id = r.sensor_id
                       WHERE r.activa""")
        cols = ("id", "codigo", "tag", "comparacion", "limite", "tipo_asfalto", "solo_en_marcha", "prioridad", "mensaje")
        _cache["reglas"] = [{c: _get(r, c, i) for i, c in enumerate(cols)} for r in cur.fetchall()]
        cur.execute("SELECT id, codigo FROM mantpred.equipos")
        _cache["equipos"] = {_get(r, "codigo", 1): _get(r, "id", 0) for r in cur.fetchall()}
    return _cache


def _get(fila, clave, indice):
    return fila[clave] if isinstance(fila, dict) else fila[indice]


def limpiar_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------- guardado
def guardar_registro(cur, registro: dict, fuente: str = "simulado", codigo_equipo: str = "MC-01") -> dict:
    """Guarda un registro de la Lambda de inferencia. Devuelve un resumen de lo escrito."""
    cat = _catalogos(cur)
    equipo_id = cat["equipos"].get(codigo_equipo)
    if equipo_id is None:
        raise ValueError(f"No existe el equipo {codigo_equipo}")

    lectura = dict(registro.get("lectura") or registro.get("lectura_actual") or {})
    t = _instante(registro.get("timestamp", lectura.get("timestamp")))
    minuto = t.replace(second=0, microsecond=0)
    hora = minuto.replace(minute=0)

    estado_txt = str(registro.get("estado_operacion") or lectura.get("ESTADO_operacion") or "").strip().lower()
    estado = ESTADOS.get(estado_txt) or ("limpieza" if str(lectura.get("en_limpieza")) == "1" else "produccion")
    tipo_txt = str(lectura.get("TIPO_asfalto") or "").strip().lower()
    tipo = TIPOS.get(tipo_txt) or ("plastomerico" if str(lectura.get("es_plastomerico")) == "1" else
                                   ("ninguno" if estado == "detenida" else "convencional"))
    en_marcha = estado in EN_MARCHA
    resumen = {"ts": minuto.isoformat(), "estado": estado, "lecturas": 0, "predicciones": 0, "condiciones": []}

    # 1. Estado del minuto (si ya existía, el minuto ya fue procesado: solo se actualiza la predicción)
    cur.execute("""INSERT INTO mantpred.estados_equipo (equipo_id, ts, estado, tipo_asfalto, fuente)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (equipo_id, fuente, ts) DO NOTHING""",
                (equipo_id, minuto, estado, tipo, fuente))
    minuto_nuevo = cur.rowcount == 1

    if minuto_nuevo:
        # 2. Lecturas del minuto
        ids, valores = [], []
        for tag, sid in cat["sensores"].items():
            if tag in lectura:
                v = _num(lectura[tag])
                if v is not None:
                    ids.append(sid); valores.append(v)
        if ids:
            cur.execute("""INSERT INTO mantpred.lecturas (sensor_id, ts, valor, fuente)
                           SELECT unnest(%s::int[]), %s, unnest(%s::numeric[]), %s
                           ON CONFLICT (sensor_id, fuente, ts) DO NOTHING""",
                        (ids, minuto, valores, fuente))
            resumen["lecturas"] = len(ids)

        # 3. Diagnóstico y vigilancia del minuto
        diag = registro.get("diagnostico") or {}
        vig = registro.get("vigilancia") or registro.get("vigilancia_autoencoder") or {}
        falla_diag = None
        if diag:
            anomalia = bool(diag.get("anomalia_confirmada"))
            falla_diag = diag.get("falla") if anomalia and diag.get("falla") not in (None, "Normal") else None
            info = cat["fallas"].get(falla_diag) if falla_diag else None
            cur.execute(
                """INSERT INTO mantpred.predicciones
                       (equipo_id, ts, modelo, modelo_version, horizonte, tipo_falla_id, prob_falla,
                        metodo, alerta, detalle, fuente)
                   VALUES (%s, %s, 'diagnostico', %s, 'actual', %s, %s, 'LightGBM', %s, %s, %s)
                   ON CONFLICT (equipo_id, fuente, modelo, ts) WHERE modelo IN ('diagnostico', 'autoencoder')
                   DO NOTHING""",
                (equipo_id, minuto, str(registro.get("version_modelo", "lambda"))[:30],
                 info["id"] if info else None, _prob(diag.get("probabilidad_etapa1")), bool(falla_diag),
                 json.dumps({"falla": diag.get("falla"), "confianza_etapa2": diag.get("confianza_etapa2"),
                             "accion": diag.get("accion")}), fuente))
            resumen["predicciones"] += cur.rowcount

        sensores_ae = []
        alerta_ae = False
        if vig:
            mse = _num(vig.get("mse"))
            umbral = _num(vig.get("umbral"))
            alerta_ae = bool(vig.get("alerta_anomalia_nueva"))
            ratio = _num(vig.get("indice_salud_ratio"))
            total = (mse or 0) * N_VARIABLES_AE
            for s in vig.get("sensores_mayor_desviacion") or []:
                e = _num(s.get("error_cuadratico")) or 0.0
                sensores_ae.append({"tag": s.get("sensor"), "error": e,
                                    "porcentaje": min(100.0, round(100 * e / total, 1)) if total else None})
            indice = max(0.0, 100.0 - min(100.0, ratio * 25.0)) if ratio is not None else None
            cur.execute(
                """INSERT INTO mantpred.predicciones
                       (equipo_id, ts, modelo, modelo_version, horizonte, prob_falla, indice_salud,
                        metodo, umbral, alerta, error_ae, detalle, fuente)
                   VALUES (%s, %s, 'autoencoder', %s, 'actual', NULL, %s, 'Autoencoder', %s, %s, %s, %s, %s)
                   ON CONFLICT (equipo_id, fuente, modelo, ts) WHERE modelo IN ('diagnostico', 'autoencoder')
                   DO NOTHING""",
                (equipo_id, minuto, str(registro.get("version_modelo", "lambda"))[:30], indice, umbral,
                 alerta_ae, mse, json.dumps({"sensores": sensores_ae}), fuente))
            resumen["predicciones"] += cur.rowcount

        # 4. Condiciones anómalas del minuto
        condiciones = []
        if en_marcha:
            if falla_diag:
                condiciones.append(("modelo:" + falla_diag, "modelo", falla_diag, None,
                                    _prob(diag.get("confianza_etapa2"))))
            elif alerta_ae:
                rara = next((SENSORES_FALLA_RARA[s["tag"]] for s in sensores_ae
                             if s["tag"] in SENSORES_FALLA_RARA), None)
                falla = rara or ANOMALIA_DESCONOCIDA
                condiciones.append(("modelo:" + falla, "modelo", falla, None, _num(vig.get("mse"))))
        for r in cat["reglas"]:
            if r["solo_en_marcha"] and not en_marcha:
                continue
            if r["tipo_asfalto"] and r["tipo_asfalto"] != tipo:
                continue
            v = _num(lectura.get(r["tag"]))
            if v is None:
                continue
            limite = float(r["limite"])
            if (r["comparacion"] == ">" and v > limite) or (r["comparacion"] == "<" and v < limite):
                condiciones.append(("regla:" + r["codigo"], "regla", None, r["id"], v))
        for clave, origen, falla, regla_id, valor in condiciones:
            info = cat["fallas"].get(falla) if falla else None
            cur.execute(
                """INSERT INTO mantpred.condiciones_minuto
                       (equipo_id, fuente, ts, clave, origen, tipo_falla_id, regla_id, valor)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (equipo_id, fuente, minuto, clave[:80], origen, info["id"] if info else None, regla_id, valor))
        resumen["condiciones"] = [c[0] for c in condiciones]

        # 5. Alarmas
        resumen["alarmas"] = evaluar_alarmas(cur, equipo_id, fuente, minuto, confirmado_ae=alerta_ae,
                                             sensores_ae=sensores_ae)

    # 6. Predicción (una fila por hora, falla y horizonte; se actualiza con el último cálculo de la hora)
    pron = (registro.get("predictivo") or {}).get("pronosticos") or {}
    for falla, p in pron.items():
        info = cat["fallas"].get(falla)
        if info is None:
            continue
        for hz_txt, h in (p.get("horizontes") or {}).items():
            hz = HORIZONTES.get(hz_txt)
            if hz is None:
                continue
            cur.execute(
                """INSERT INTO mantpred.predicciones
                       (equipo_id, ts, modelo, modelo_version, horizonte, tipo_falla_id, prob_falla,
                        metodo, umbral, alerta, dias_estimados, fuente)
                   VALUES (%s, %s, 'predictivo', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (equipo_id, fuente, tipo_falla_id, horizonte, ts) WHERE modelo = 'predictivo'
                   DO UPDATE SET prob_falla = EXCLUDED.prob_falla, umbral = EXCLUDED.umbral,
                                 alerta = EXCLUDED.alerta, dias_estimados = EXCLUDED.dias_estimados,
                                 metodo = EXCLUDED.metodo""",
                (equipo_id, hora, str(registro.get("version_modelo", "lambda"))[:30], hz, info["id"],
                 _prob(h.get("probabilidad")), str(p.get("metodo") or "")[:20] or None, _num(h.get("umbral")),
                 bool(h.get("alerta")), _dias(p.get("dias_estimados")), fuente))
            resumen["predicciones"] += 1
    return resumen


def _prob(v) -> float | None:
    f = _num(v)
    return None if f is None else max(0.0, min(1.0, f))


def _dias(v) -> float | None:
    f = _num(v)
    return None if f is None else min(f, 99999999.0)


# ---------------------------------------------------------------- alarmas
def evaluar_alarmas(cur, equipo_id: int, fuente: str, minuto: dt.datetime, confirmado_ae: bool = False,
                    sensores_ae: list | None = None) -> dict:
    """Abre o cierra alarmas según las condiciones de los últimos 5 minutos con datos."""
    cat = _cache
    cur.execute("""SELECT min(ts) AS desde FROM (
                       SELECT ts FROM mantpred.estados_equipo
                       WHERE equipo_id = %s AND fuente = %s AND ts <= %s ORDER BY ts DESC LIMIT 5) u""",
                (equipo_id, fuente, minuto))
    desde = _get(cur.fetchone(), "desde", 0)
    cur.execute("""SELECT clave, min(origen) AS origen, min(tipo_falla_id) AS tipo_falla_id,
                          min(regla_id) AS regla_id, count(*) AS minutos, min(ts) AS primera,
                          (array_agg(valor ORDER BY ts DESC))[1] AS valor
                   FROM mantpred.condiciones_minuto
                   WHERE equipo_id = %s AND fuente = %s AND ts BETWEEN %s AND %s
                   GROUP BY clave""", (equipo_id, fuente, desde, minuto))
    cols = ("clave", "origen", "tipo_falla_id", "regla_id", "minutos", "primera", "valor")
    ventana = {_get(r, "clave", 0): {c: _get(r, c, i) for i, c in enumerate(cols)} for r in cur.fetchall()}

    cur.execute("""SELECT id, clave FROM mantpred.alarmas
                   WHERE equipo_id = %s AND fuente = %s AND fin IS NULL""", (equipo_id, fuente))
    activas = {_get(r, "clave", 1): _get(r, "id", 0) for r in cur.fetchall()}

    abiertas, cerradas = [], []
    for clave, c in ventana.items():
        if c["minutos"] >= 3 and clave not in activas:
            if c["origen"] == "regla":
                regla = next(r for r in cat["reglas"] if r["id"] == c["regla_id"])
                prioridad, mensaje, tf = regla["prioridad"], regla["mensaje"], None
                detalle = {"origen": "regla fija"}
            else:
                falla = next((k for k, v in cat["fallas"].items() if v["id"] == c["tipo_falla_id"]), None)
                info = cat["fallas"].get(falla, {})
                prioridad, mensaje, tf = info.get("prioridad", "media"), info.get("titulo"), c["tipo_falla_id"]
                if falla == ANOMALIA_DESCONOCIDA:
                    origen_txt = "autoencoder"
                elif confirmado_ae:
                    origen_txt = "diagnóstico, confirmado por el autoencoder"
                elif falla in SENSORES_FALLA_RARA.values() and not _hubo_diagnostico(cur, equipo_id, fuente, desde, minuto, tf):
                    origen_txt = "autoencoder (sensores de falla rara)"
                else:
                    origen_txt = "diagnóstico"
                detalle = {"origen": origen_txt, "sensores": sensores_ae or []}
            cur.execute(
                """INSERT INTO mantpred.alarmas (equipo_id, origen, tipo_falla_id, regla_id, inicio, valor,
                                                 severidad, mensaje, fuente, clave, detalle)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (equipo_id, c["origen"], tf, c["regla_id"], c["primera"], c["valor"],
                 PRIORIDAD_A_SEVERIDAD.get(prioridad, "advertencia"), (mensaje or clave)[:250], fuente, clave,
                 json.dumps(detalle)))
            abiertas.append(clave)
    for clave, alarma_id in activas.items():
        if ventana.get(clave, {}).get("minutos", 0) <= 1:
            cur.execute("UPDATE mantpred.alarmas SET fin = %s WHERE id = %s AND inicio <= %s",
                        (minuto, alarma_id, minuto))
            cerradas.append(clave)
    return {"abiertas": abiertas, "cerradas": cerradas}


def _hubo_diagnostico(cur, equipo_id, fuente, desde, hasta, tipo_falla_id) -> bool:
    cur.execute("""SELECT 1 FROM mantpred.predicciones
                   WHERE equipo_id = %s AND fuente = %s AND modelo = 'diagnostico'
                     AND ts BETWEEN %s AND %s AND tipo_falla_id = %s LIMIT 1""",
                (equipo_id, fuente, desde, hasta, tipo_falla_id))
    return cur.fetchone() is not None


# ---------------------------------------------------------------- simulación
def reiniciar_desde(cur, equipo_id: int, fuente: str, desde: dt.datetime) -> dict:
    """Al saltar a otra fecha de la simulación (HU-17): cierra las alarmas activas y borra lo
    simulado desde 'desde' en adelante, para que el dashboard no mezcle el futuro con el presente."""
    borrado = {}
    for tabla, col in (("lecturas", "ts"), ("estados_equipo", "ts"), ("predicciones", "ts"),
                       ("condiciones_minuto", "ts"), ("alarmas", "inicio")):
        if tabla == "lecturas":
            cur.execute("""DELETE FROM mantpred.lecturas l USING mantpred.sensores s
                           WHERE s.id = l.sensor_id AND s.equipo_id = %s AND l.fuente = %s AND l.ts >= %s""",
                        (equipo_id, fuente, desde))
        else:
            cur.execute(f"DELETE FROM mantpred.{tabla} WHERE equipo_id = %s AND fuente = %s AND {col} >= %s",
                        (equipo_id, fuente, desde))
        borrado[tabla] = cur.rowcount
    cur.execute("UPDATE mantpred.alarmas SET fin = %s WHERE equipo_id = %s AND fuente = %s AND fin IS NULL",
                (desde, equipo_id, fuente))
    borrado["alarmas_cerradas"] = cur.rowcount
    return borrado
