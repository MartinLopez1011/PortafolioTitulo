"""Datos de la planta para el dashboard: sensores, lecturas, estado, alarmas, predicciones y mantenimientos."""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import config
from ..db import cursor
from ..iot_ws import AWS_REGION, IOT_ENDPOINT, generar_iot_websocket_url
from ..seguridad import OPERADOR, auditar, ip_cliente, requiere_nivel

router = APIRouter(tags=["Planta y dashboard"])
lector = requiere_nivel(OPERADOR)          # operador y administrador ven todo el sistema

Fuente = Literal["simulado", "real"]
PASOS = {"1min": "1 minute", "5min": "5 minutes", "15min": "15 minutes", "1h": "1 hour", "1d": "1 day"}
MAX_PUNTOS = 20000

# Última lectura de cada sensor. Se busca primero max(ts) y luego la fila, para que PostgreSQL use el
# índice (sensor_id, fuente, ts). Con "ORDER BY ts DESC LIMIT 1" elegía el índice por fecha y, para
# sensores sin datos, recorría toda la tabla (650 ms frente a 1 ms medidos con 400 mil lecturas).
_ULTIMA_LECTURA = """
    JOIN LATERAL (SELECT max(ts) AS ts FROM mantpred.lecturas
                  WHERE sensor_id = s.id AND fuente = %s) m ON TRUE
    JOIN mantpred.lecturas l ON l.sensor_id = s.id AND l.fuente = %s AND l.ts = m.ts"""


def _equipo_id(cur, codigo: str) -> int:
    cur.execute("SELECT id FROM mantpred.equipos WHERE codigo = %s", (codigo,))
    fila = cur.fetchone()
    if fila is None:
        raise HTTPException(404, f"No existe el equipo {codigo}")
    return fila["id"]


# ---------------------------------------------------------------- catálogos
@router.get("/equipos", summary="Equipos monitoreados")
def equipos(u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        return demo_store.EQUIPOS
    with cursor() as cur:
        cur.execute("SELECT id, codigo, nombre, tipo, marca, modelo, potencia, ubicacion FROM mantpred.equipos ORDER BY codigo")
        return cur.fetchall()


@router.get("/sensores", summary="Catálogo de sensores")
def sensores(equipo: str = config.EQUIPO_POR_DEFECTO, origen: Fuente | None = None, u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        if origen:
            return [s for s in demo_store.SENSORES if s.get("origen") == origen]
        return demo_store.SENSORES
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        cur.execute(
            """SELECT s.id, s.tag, s.nombre, c.codigo AS componente, s.variable, s.tipo_sensor, s.unidad,
                      s.rango_min, s.rango_max, s.normal_min, s.normal_max, s.senal, s.origen, s.activo
               FROM mantpred.sensores s JOIN mantpred.componentes c ON c.id = s.componente_id
               WHERE s.equipo_id = %s AND (%s::text IS NULL OR s.origen = %s) ORDER BY c.codigo, s.tag""",
            (eq, origen, origen))
        return cur.fetchall()


@router.get("/tipos-falla", summary="Catálogo de fallas que reconoce el modelo")
def tipos_falla(u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        return demo_store.TIPOS_FALLA
    with cursor() as cur:
        cur.execute("""SELECT tf.id, tf.codigo, tf.titulo, c.codigo AS componente, tf.prioridad, tf.accion
                       FROM mantpred.tipos_falla tf LEFT JOIN mantpred.componentes c ON c.id = tf.componente_id
                       ORDER BY tf.id""")
        return cur.fetchall()


# ---------------------------------------------------------------- lecturas
@router.get("/lecturas/ultimas", summary="Último valor de cada sensor (tarjetas en tiempo real)")
def lecturas_ultimas(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado",
                     u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        return demo_store.obtener_lecturas_demo()
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        cur.execute(
            f"""SELECT s.id AS sensor_id, s.tag, s.nombre, c.codigo AS componente, s.variable, s.unidad,
                       s.normal_min, s.normal_max, l.ts, l.valor, l.calidad,
                       (l.valor < s.normal_min OR l.valor > s.normal_max) AS fuera_de_rango
                FROM mantpred.sensores s JOIN mantpred.componentes c ON c.id = s.componente_id {_ULTIMA_LECTURA}
                WHERE s.equipo_id = %s AND s.activo
                ORDER BY c.codigo, s.tag""", (fuente, fuente, eq))
        return cur.fetchall()


@router.get("/lecturas/serie", summary="Serie de tiempo de uno o más sensores (gráficos)")
def lecturas_serie(
        tags: str = Query(..., description="Tags separados por coma, por ejemplo TEM_son_betum_in,AMP_vfd_motor_molino"),
        desde: dt.datetime | None = Query(None, description="Inicio (ISO 8601). Por defecto, 24 h antes de 'hasta'"),
        hasta: dt.datetime | None = Query(None, description="Fin (ISO 8601). Por defecto, la última lectura disponible"),
        paso: Literal["1min", "5min", "15min", "1h", "1d"] = "15min",
        fuente: Fuente = "simulado",
        u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        import math as _m
        from .. import demo_store
        lista = [t.strip() for t in tags.split(",") if t.strip()]
        ahora = hasta or demo_store._avanzar_reloj_demo()
        esc = demo_store.SIM_ESTADO.get("escenario", "")
        series = []
        for idx, t in enumerate(lista):
            base = float(demo_store.VALORES_INICIALES.get(t, 25.0))
            pts = []
            for p_idx in range(36, -1, -1):
                pt_t = ahora - dt.timedelta(minutes=p_idx * 20)
                prog = (36 - p_idx) / 36.0
                onda = _m.sin(p_idx * 0.45 + idx) * (base * 0.025 if base else 0.05)
                deriva = 0.0
                if esc == "filtro" and t == "PRE_dif_filtro_bar":
                    deriva = 1.05 * (prog ** 1.8)
                elif esc == "filtro" and t == "CAU_bomba_lpm":
                    deriva = -48.0 * (prog ** 1.6)
                elif esc == "caldera" and t == "TEM_son_betum_in":
                    deriva = -18.0 * prog
                elif esc == "caldera" and t in ("AMP_vfd_motor_molino", "TOR_vfd_motor_molino"):
                    deriva = 22.0 * (prog ** 1.4)
                elif esc == "rodamientos" and t == "VIB_vel_motor_molino":
                    deriva = 2.2 * (prog ** 1.5)
                val = round(base + onda + deriva, 2)
                pts.append({"t": pt_t, "prom": val, "min": round(val * 0.98, 2), "max": round(val * 1.02, 2)})
            unidad_tag = next((s["unidad"] for s in demo_store.SENSORES if s["tag"] == t), "")
            series.append({"tag": t, "unidad": unidad_tag, "puntos": pts})
        return {"desde": ahora - dt.timedelta(hours=12), "hasta": ahora, "paso": paso, "series": series}

    lista = [t.strip() for t in tags.split(",") if t.strip()]
    if not lista or len(lista) > 12:
        raise HTTPException(422, "Indique entre 1 y 12 tags")
    with cursor() as cur:
        cur.execute("SELECT id, tag, unidad FROM mantpred.sensores WHERE tag = ANY(%s)", (lista,))
        sens = cur.fetchall()
        faltan = set(lista) - {s["tag"] for s in sens}
        if faltan:
            raise HTTPException(404, f"Tags no encontrados: {', '.join(sorted(faltan))}")
        ids = [s["id"] for s in sens]
        if hasta is None:
            cur.execute("SELECT max(ts) AS m FROM mantpred.lecturas WHERE sensor_id = ANY(%s) AND fuente = %s",
                        (ids, fuente))
            hasta = cur.fetchone()["m"]
            if hasta is None:
                return {"desde": None, "hasta": None, "paso": paso, "series": []}
        if desde is None:
            desde = hasta - dt.timedelta(hours=24)
        if desde >= hasta:
            raise HTTPException(422, "'desde' debe ser anterior a 'hasta'")
        cur.execute(
            """SELECT s.tag, date_bin(%s::interval, l.ts, TIMESTAMPTZ '2000-01-01') AS t,
                      avg(l.valor)::numeric(12,3) AS prom, min(l.valor) AS min, max(l.valor) AS max
               FROM mantpred.lecturas l JOIN mantpred.sensores s ON s.id = l.sensor_id
               WHERE l.sensor_id = ANY(%s) AND l.fuente = %s AND l.ts >= %s AND l.ts <= %s
               GROUP BY s.tag, t ORDER BY s.tag, t LIMIT %s""",
            (PASOS[paso], ids, fuente, desde, hasta, MAX_PUNTOS + 1))
        filas = cur.fetchall()
    if len(filas) > MAX_PUNTOS:
        raise HTTPException(422, "Demasiados puntos; use un paso mayor o un rango más corto")
    unidades = {s["tag"]: s["unidad"] for s in sens}
    series = {t: [] for t in lista}
    for f in filas:
        series[f["tag"]].append({"t": f["t"], "prom": f["prom"], "min": f["min"], "max": f["max"]})
    return {"desde": desde, "hasta": hasta, "paso": paso,
            "series": [{"tag": t, "unidad": unidades[t], "puntos": series[t]} for t in lista]}


# ---------------------------------------------------------------- estado del equipo
@router.get("/estado/actual", summary="Estado de operación más reciente")
def estado_actual(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado", u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        return {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "estado": "produccion", "tipo_asfalto": "convencional"}
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        cur.execute(
            """SELECT ts, estado, tipo_asfalto FROM mantpred.estados_equipo
               WHERE equipo_id = %s AND fuente = %s ORDER BY ts DESC LIMIT 1""", (eq, fuente))
        return cur.fetchone() or {"ts": None, "estado": None, "tipo_asfalto": None}


@router.get("/estado/historial", summary="Tramos de operación (cada cambio de estado)")
def estado_historial(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado",
                     desde: dt.datetime | None = None, hasta: dt.datetime | None = None,
                     u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        return demo_store.obtener_historial_estado_demo()
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        if hasta is None:
            cur.execute("SELECT max(ts) AS m FROM mantpred.estados_equipo WHERE equipo_id = %s AND fuente = %s",
                        (eq, fuente))
            hasta = cur.fetchone()["m"]
            if hasta is None:
                return []
        desde = desde or hasta - dt.timedelta(days=7)
        cur.execute(
            """WITH e AS (
                   SELECT ts, estado, tipo_asfalto,
                          lag(estado) OVER (ORDER BY ts) IS DISTINCT FROM estado
                          OR lag(tipo_asfalto) OVER (ORDER BY ts) IS DISTINCT FROM tipo_asfalto AS cambio
                   FROM mantpred.estados_equipo
                   WHERE equipo_id = %s AND fuente = %s AND ts BETWEEN %s AND %s),
               g AS (SELECT *, sum(cambio::int) OVER (ORDER BY ts) AS grupo FROM e)
               SELECT min(ts) AS inicio, max(ts) AS fin, estado, tipo_asfalto,
                       count(*) AS minutos
               FROM g GROUP BY grupo, estado, tipo_asfalto ORDER BY inicio""",
            (eq, fuente, desde, hasta))
        return cur.fetchall()


@router.get("/resumen", summary="Indicadores para el encabezado del dashboard")
def resumen(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado", u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        r = demo_store.obtener_resumen_demo()
        r["equipo"] = {"codigo": "MC-01", "nombre": "Molino coloidal HP 240"}
        r["fuente"] = fuente
        return r
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        cur.execute("SELECT codigo, nombre FROM mantpred.equipos WHERE id = %s", (eq,))
        info = cur.fetchone()
        cur.execute(
            """SELECT ts, estado, tipo_asfalto FROM mantpred.estados_equipo
               WHERE equipo_id = %s AND fuente = %s ORDER BY ts DESC LIMIT 1""", (eq, fuente))
        est = cur.fetchone() or {}
        cur.execute(
            f"""SELECT count(*) FILTER (WHERE l.valor < s.normal_min OR l.valor > s.normal_max) AS fuera,
                       count(*) AS total, max(l.ts) AS ultima
                FROM mantpred.sensores s {_ULTIMA_LECTURA}
                WHERE s.equipo_id = %s AND s.activo""", (fuente, fuente, eq))
        sens = cur.fetchone()
        cur.execute(
            """SELECT count(*) AS activas, count(*) FILTER (WHERE reconocida_en IS NULL) AS sin_reconocer
               FROM mantpred.alarmas WHERE equipo_id = %s AND fin IS NULL AND fuente = %s""", (eq, fuente))
        alm = cur.fetchone()
    return {"equipo": info, "fuente": fuente, "ultima_lectura": sens["ultima"],
            "estado": est.get("estado"), "tipo_asfalto": est.get("tipo_asfalto"),
            "sensores_con_datos": sens["total"], "sensores_fuera_de_rango": sens["fuera"],
            "alarmas_activas": alm["activas"], "alarmas_sin_reconocer": alm["sin_reconocer"]}


# ---------------------------------------------------------------- alarmas
class Reconocimiento(BaseModel):
    comentario: str | None = Field(default=None, max_length=250)


@router.get("/alarmas", summary="Alarmas activas o recientes")
def alarmas(activas: bool = True, limite: int = Query(100, ge=1, le=500), fuente: Fuente = "simulado",
            u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        return []
    with cursor() as cur:
        cur.execute(
            """SELECT a.id, e.codigo AS equipo, a.origen, a.severidad, a.inicio, a.fin, a.valor, a.fuente,
                      COALESCE(a.mensaje, tf.titulo) AS mensaje, tf.accion, s.tag AS sensor,
                      a.reconocida_en, ur.nombre AS reconocida_por, a.comentario
               FROM mantpred.alarmas a
               JOIN mantpred.equipos e ON e.id = a.equipo_id
               LEFT JOIN mantpred.tipos_falla tf ON tf.id = a.tipo_falla_id
               LEFT JOIN mantpred.reglas_alarma r ON r.id = a.regla_id
               LEFT JOIN mantpred.sensores s ON s.id = r.sensor_id
               LEFT JOIN mantpred.usuarios ur ON ur.id = a.reconocida_por
               WHERE a.fuente = %s AND (NOT %s OR a.fin IS NULL)
               ORDER BY a.inicio DESC LIMIT %s""", (fuente, activas, limite))
        return cur.fetchall()


@router.post("/alarmas/{alarma_id}/reconocer", summary="Reconocer una alarma (operador o superior)")
def reconocer(alarma_id: int, datos: Reconocimiento, request: Request,
              u: dict = Depends(requiere_nivel(OPERADOR))):
    from .. import db
    if db.MODO_DEMO:
        return {"mensaje": "Alarma reconocida (modo demostración)"}
    with cursor() as cur:
        cur.execute(
            """UPDATE mantpred.alarmas SET reconocida_por = %s, reconocida_en = now(), comentario = %s
               WHERE id = %s AND reconocida_en IS NULL RETURNING id""",
            (u["id"], datos.comentario, alarma_id))
        if cur.fetchone() is None:
            cur.execute("SELECT 1 FROM mantpred.alarmas WHERE id = %s", (alarma_id,))
            if cur.fetchone() is None:
                raise HTTPException(404, "Alarma no encontrada")
            raise HTTPException(409, "La alarma ya fue reconocida")
        auditar(cur, u["id"], u["email"], ip_cliente(request), "alarma_reconocida", f"alarma {alarma_id}")
    return {"mensaje": "Alarma reconocida"}


# ---------------------------------------------------------------- predicciones
@router.get("/predicciones/ultimas", summary="Última predicción de cada modelo y horizonte")
def predicciones_ultimas(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente = "simulado",
                         u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO:
        from .. import demo_store
        return demo_store.obtener_predicciones_demo()
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        cur.execute(
            """SELECT DISTINCT ON (p.modelo, p.horizonte, p.tipo_falla_id)
                      p.ts, p.modelo, p.modelo_version, p.horizonte, tf.codigo AS falla, tf.titulo,
                      p.prob_falla, p.indice_salud, p.alerta, p.umbral
               FROM mantpred.predicciones p LEFT JOIN mantpred.tipos_falla tf ON tf.id = p.tipo_falla_id
               WHERE p.equipo_id = %s AND p.fuente = %s
               ORDER BY p.modelo, p.horizonte, p.tipo_falla_id, p.ts DESC""", (eq, fuente))
        return cur.fetchall()


# ---------------------------------------------------------------- mantenimientos
class MantenimientoNuevo(BaseModel):
    clave_equipo: str | None = Field(
        default=None, max_length=30,
        description="Clave del punto de mantención (filtro, radar, caldera, intercambiador, caudalimetro, pt100, rodamientos, planta_completa)",
    )
    componente: str | None = Field(default=None, max_length=20,
                                   description="Código del componente (F-101, TK-101...). Vacío = toda la línea")
    tipo: Literal["preventivo", "correctivo", "predictivo"]
    fecha_inicio: dt.datetime
    fecha_fin: dt.datetime | None = None
    fallas: list[str] = Field(default_factory=list, max_length=8,
                              description="Códigos de tipos_falla que atiende la intervención")
    alarma_id: int | None = None
    descripcion: str | None = Field(default=None, max_length=2000)
    fuente: Fuente = "simulado"


def _normalizar_fecha_planta(fecha: dt.datetime | None) -> dt.datetime | None:
    if fecha is None:
        return None
    if fecha.tzinfo is None:
        from zoneinfo import ZoneInfo
        fecha = fecha.replace(tzinfo=ZoneInfo(config.ZONA_HORARIA))
    return fecha.astimezone(dt.timezone.utc)


@router.get("/mantenimientos", summary="Historial de mantenimientos")
def mantenimientos(equipo: str = config.EQUIPO_POR_DEFECTO, fuente: Fuente | None = None,
                   limite: int = Query(100, ge=1, le=500), u: dict = Depends(lector)):
    from .. import db
    if db.MODO_DEMO or config.MODO_DEMO:
        from .. import demo_store
        return demo_store.obtener_mantenimiento_demo()["bitacora"][:limite]
    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        cur.execute(
            """SELECT m.id, c.codigo AS componente, m.tipo, m.alarma_id, m.fecha_inicio, m.fecha_fin,
                      m.descripcion, m.fuente, m.origen_registro, us.nombre AS registrado_por,
                      (SELECT array_agg(tf.codigo ORDER BY tf.id) FROM mantpred.mantenimiento_fallas mf
                       JOIN mantpred.tipos_falla tf ON tf.id = mf.tipo_falla_id
                       WHERE mf.mantenimiento_id = m.id) AS fallas
               FROM mantpred.mantenimientos m
               LEFT JOIN mantpred.componentes c ON c.id = m.componente_id
               LEFT JOIN mantpred.usuarios us ON us.id = m.registrado_por
               WHERE m.equipo_id = %s AND (%s::text IS NULL OR m.fuente = %s)
               ORDER BY m.fecha_inicio DESC, m.id DESC LIMIT %s""", (eq, fuente, fuente, limite))
        return cur.fetchall()


@router.post("/mantenimientos", status_code=201, summary="Registrar un mantenimiento (operador o administrador)")
def crear_mantenimiento(datos: MantenimientoNuevo, request: Request, equipo: str = config.EQUIPO_POR_DEFECTO,
                        u: dict = Depends(requiere_nivel(OPERADOR))):
    from .. import db
    from .pantallas import EQUIPOS as PUNTOS_EQUIPO

    f_inicio = _normalizar_fecha_planta(datos.fecha_inicio)
    f_fin = _normalizar_fecha_planta(datos.fecha_fin)
    if f_fin and f_fin < f_inicio:
        raise HTTPException(422, "La fecha de término no puede ser anterior a la fecha de inicio")

    por_clave = {e["clave"]: e for e in PUNTOS_EQUIPO}
    componente_cod = (datos.componente or "").strip() or None
    fallas_lista = list(datos.fallas or [])
    nombre_comp_demo = "Planta completa"

    if datos.clave_equipo:
        clave = datos.clave_equipo.strip()
        if clave == "planta_completa":
            componente_cod = None
            nombre_comp_demo = "Planta completa"
            if not fallas_lista:
                fallas_lista = [e["falla"] for e in PUNTOS_EQUIPO]
        elif clave in por_clave:
            punto = por_clave[clave]
            componente_cod = componente_cod or punto["componente"]
            nombre_comp_demo = punto["equipo"]
            if not fallas_lista:
                fallas_lista = [punto["falla"]]
        else:
            raise HTTPException(422, f"Equipo de mantención desconocido: {clave}")
    elif componente_cod:
        coincidencias = [e for e in PUNTOS_EQUIPO if e["componente"] == componente_cod]
        if coincidencias:
            nombre_comp_demo = coincidencias[0]["equipo"]
            if not fallas_lista and len(coincidencias) == 1:
                fallas_lista = [coincidencias[0]["falla"]]
        else:
            nombre_comp_demo = componente_cod

    fallas = sorted(set(fallas_lista))
    descripcion = (datos.descripcion or "").strip() or None

    if db.MODO_DEMO or config.MODO_DEMO:
        from .. import demo_store
        codigos_validos = {f["codigo"] for f in demo_store.TIPOS_FALLA}
        faltan_demo = set(fallas) - codigos_validos
        if faltan_demo:
            raise HTTPException(422, f"Tipos de falla desconocidos: {', '.join(sorted(faltan_demo))}")
        reg = demo_store.registrar_mantenimiento_demo(
            componente_nombre=nombre_comp_demo,
            codigo_componente=componente_cod,
            tipo=datos.tipo,
            fecha_inicio=f_inicio,
            fecha_fin=f_fin,
            fallas=fallas,
            descripcion=descripcion,
            registrado_por=u.get("nombre") or u.get("email") or "Operador",
            fuente=datos.fuente,
        )
        return {"id": reg["id"], "mensaje": "Mantenimiento registrado", "mantenimiento": reg}

    with cursor() as cur:
        eq = _equipo_id(cur, equipo)
        componente_id = None
        if componente_cod:
            cur.execute("SELECT id FROM mantpred.componentes WHERE codigo = %s AND equipo_id = %s",
                        (componente_cod, eq))
            fila = cur.fetchone()
            if fila is None:
                raise HTTPException(422, f"Componente desconocido: {componente_cod}")
            componente_id = fila["id"]
        cur.execute("SELECT id, codigo FROM mantpred.tipos_falla WHERE codigo = ANY(%s)", (fallas,))
        ids_falla = {f["codigo"]: f["id"] for f in cur.fetchall()}
        faltan = set(fallas) - set(ids_falla)
        if faltan:
            raise HTTPException(422, f"Tipos de falla desconocidos: {', '.join(sorted(faltan))}")
        cur.execute(
            """INSERT INTO mantpred.mantenimientos
                   (equipo_id, registrado_por, componente_id, tipo, alarma_id,
                    fecha_inicio, fecha_fin, descripcion, fuente, origen_registro)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'dashboard') RETURNING id""",
            (eq, u["id"], componente_id, datos.tipo, datos.alarma_id,
             f_inicio, f_fin, descripcion, datos.fuente))
        nuevo = cur.fetchone()["id"]
        if ids_falla:
            cur.execute("""INSERT INTO mantpred.mantenimiento_fallas (mantenimiento_id, tipo_falla_id)
                           SELECT %s, unnest(%s::smallint[])""", (nuevo, list(ids_falla.values())))
        auditar(cur, u["id"], u["email"], ip_cliente(request), "mantenimiento_registrado",
                f"id {nuevo} ({datos.tipo})")

    if datos.fuente == "simulado":
        try:
            import threading
            from ..simulador import simulador
            if simulador.reloj is not None:
                t_ref = max(simulador.reloj.to_pydatetime(), f_inicio)
                threading.Thread(target=simulador._escribir_bitacora, args=(t_ref,), daemon=True).start()
        except Exception:
            pass

    return {"id": nuevo, "mensaje": "Mantenimiento registrado"}


@router.get("/iot/ws-url", summary="URL pre-firmada WebSocket para conexión MQTT en tiempo real")
def iot_ws_url(u: dict = Depends(lector)):
    """Genera una URL pre-firmada SigV4 para conectar al broker AWS IoT Core via WebSockets."""
    url = generar_iot_websocket_url()
    return {
        "disponible": bool(url),
        "url": url,
        "endpoint": IOT_ENDPOINT,
        "region": AWS_REGION,
        "topics": {
            "telemetria": "planta/asfalto/molino/telemetria",
            "predicciones": "planta/asfalto/molino/predicciones",
        },
    }
