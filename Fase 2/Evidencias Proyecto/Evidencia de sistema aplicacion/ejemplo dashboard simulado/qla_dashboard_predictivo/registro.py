"""
Registro en SQLite, gestión de alarmas (persistencia, reconocimiento, retroalimentación) e indicadores.
"""
import json
import math
import sqlite3
import threading
from collections import deque

import config as cfg

_lock = threading.Lock()
_con = sqlite3.connect(cfg.RUTA_DB, check_same_thread=False)
_con.row_factory = sqlite3.Row
_con.executescript("""
CREATE TABLE IF NOT EXISTS lecturas (id INTEGER PRIMARY KEY, tiempo TEXT, estado TEXT, ae_error REAL);
CREATE INDEX IF NOT EXISTS idx_lecturas_tiempo ON lecturas(tiempo);
CREATE TABLE IF NOT EXISTS intervenciones (
    id INTEGER PRIMARY KEY, tiempo TEXT, equipo TEXT, clave TEXT, tipo TEXT, descripcion TEXT, usuario TEXT
);
CREATE TABLE IF NOT EXISTS alarmas (
    id INTEGER PRIMARY KEY, clave TEXT, titulo TEXT, tipo TEXT, prioridad TEXT,
    fuente TEXT, inicio TEXT, fin TEXT, origen TEXT, sensores TEXT, lecturas_inicio TEXT,
    reconocida_en TEXT, reconocida_por TEXT, feedback TEXT, feedback_texto TEXT, feedback_en TEXT
);
""")
_con.commit()


def _q(sql, args=(), uno=False):
    with _lock:
        cur = _con.execute(sql, args)
        _con.commit()
        filas = cur.fetchall()
    filas = [dict(f) for f in filas]
    return (filas[0] if filas else None) if uno else filas


def guardar_lecturas(filas):
    with _lock:
        _con.executemany("INSERT INTO lecturas (tiempo, estado, ae_error) VALUES (?,?,?)", filas)
        _con.commit()


def limpiar_lecturas_desde(tiempo):
    """Al saltar en el tiempo se borran las lecturas posteriores para no mezclar historias."""
    _q("DELETE FROM lecturas WHERE tiempo >= ?", (tiempo.isoformat(),))


def registrar_intervencion(tiempo, equipo, clave, tipo, descripcion, usuario):
    _q("INSERT INTO intervenciones (tiempo, equipo, clave, tipo, descripcion, usuario) VALUES (?,?,?,?,?,?)",
       (tiempo.isoformat(), equipo, clave, tipo, descripcion, usuario))


def intervenciones_usuario():
    return _q("SELECT * FROM intervenciones ORDER BY tiempo")


# --------------------------------------------------------------------- alarmas
class GestorAlarmas:
    def __init__(self):
        self.ventana = deque(maxlen=cfg.PERSISTENCIA_VENTANA)
        self.activas = {}   # clave -> id

    def reiniciar(self, tiempo):
        for clave, id_ in list(self.activas.items()):
            _q("UPDATE alarmas SET fin=? WHERE id=?", (tiempo.isoformat(), id_))
        self.activas.clear()
        self.ventana.clear()

    def procesar(self, tiempo, fuente, evaluacion, lecturas, marcha):
        """Recibe la evaluación de un minuto y abre o cierra alarmas según la persistencia."""
        presentes = {}
        est = evaluacion["estado"]
        if est not in ("Normal", "Detenida"):
            f = cfg.FALLAS.get(est, cfg.FALLAS["Anomalia_Desconocida"])
            sensores = [s["id"] for s in (evaluacion["autoencoder"] or {}).get("sensores", [])]
            presentes[f"modelo:{est}"] = (f["titulo"], "modelo", f["prioridad"], evaluacion["origen"], sensores)
        for sensor, cond, valor, titulo, prioridad, solo_marcha in cfg.REGLAS:
            v = lecturas.get(sensor)
            if solo_marcha and not marcha:
                continue
            if v is not None and ((cond == "<" and v < valor) or (cond == ">" and v > valor)):
                presentes[f"limite:{sensor}"] = (titulo, "limite", prioridad, "Límite de proceso", [sensor])
        self.ventana.append(presentes)

        conteo = {}
        for paso in self.ventana:
            for clave in paso:
                conteo[clave] = conteo.get(clave, 0) + 1

        for clave, n in conteo.items():
            if clave not in self.activas and n >= cfg.PERSISTENCIA_ACTIVAR and clave in presentes:
                titulo, tipo, prioridad, origen, sensores = presentes[clave]
                _q("""INSERT INTO alarmas (clave, titulo, tipo, prioridad, fuente, inicio, origen,
                      sensores, lecturas_inicio) VALUES (?,?,?,?,?,?,?,?,?)""",
                   (clave, titulo, tipo, prioridad, fuente, tiempo.isoformat(), origen,
                    json.dumps(sensores), json.dumps(lecturas)))
                self.activas[clave] = _q("SELECT last_insert_rowid() AS id", uno=True)["id"]
        for clave in list(self.activas):
            if conteo.get(clave, 0) <= cfg.PERSISTENCIA_RESOLVER:
                _q("UPDATE alarmas SET fin=? WHERE id=?", (tiempo.isoformat(), self.activas.pop(clave)))

    def listar_activas(self):
        if not self.activas:
            return []
        ids = ",".join(str(i) for i in self.activas.values())
        return _formatear(_q(f"SELECT * FROM alarmas WHERE id IN ({ids}) ORDER BY prioridad='alta' DESC, inicio"))


def _formatear(filas):
    for f in filas:
        f["sensores"] = json.loads(f["sensores"] or "[]")
        f.pop("lecturas_inicio", None)
    return filas


def historial_alarmas(limite=200):
    return _formatear(_q("SELECT * FROM alarmas ORDER BY id DESC LIMIT ?", (limite,)))


def reconocer(id_, usuario, ahora):
    _q("UPDATE alarmas SET reconocida_en=?, reconocida_por=? WHERE id=? AND reconocida_en IS NULL",
       (ahora, usuario, id_))


def retroalimentar(id_, valor, texto, ahora):
    _q("UPDATE alarmas SET feedback=?, feedback_texto=?, feedback_en=? WHERE id=?",
       (valor, texto, ahora, id_))


def etiquetas():
    """Alarmas con retroalimentación del operador, junto a las lecturas del momento de inicio."""
    filas = _q("SELECT * FROM alarmas WHERE feedback IS NOT NULL ORDER BY id")
    salida = []
    for f in filas:
        base = {k: f[k] for k in ("id", "fuente", "inicio", "fin", "titulo", "clave", "origen",
                                   "feedback", "feedback_texto", "reconocida_por")}
        base.update(json.loads(f["lecturas_inicio"] or "{}"))
        salida.append(base)
    return salida


def salud_diaria():
    return _q("""SELECT substr(tiempo, 1, 10) AS dia, AVG(ae_error) AS error_medio,
                        COUNT(*) AS minutos, SUM(estado NOT IN ('Normal', 'Detenida')) AS minutos_anomalos
                 FROM lecturas WHERE ae_error IS NOT NULL GROUP BY dia ORDER BY dia""")


# --------------------------------------------------------------------- indicadores
class Indicadores:
    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.minutos_marcha = self.normales = 0
        self.kwh = self.litros = 0.0
        self.dia = None

    def actualizar(self, fila, estado, marcha):
        dia = fila["timestamp"].date()
        if dia != self.dia:                     # el turno se reinicia cada día
            self.reiniciar()
            self.dia = dia
        if not marcha:
            return
        self.minutos_marcha += 1
        self.normales += estado == "Normal"
        if fila["ESTADO_operacion"] == "Produccion":
            self.litros += fila["CAU_bomba_lpm"]
        self.kwh += math.sqrt(3) * cfg.VOLTAJE_MOTOR_V * fila["AMP_vfd_motor_molino"] * cfg.FACTOR_POTENCIA / 1000 / 60

    def resumen(self, fila):
        r = cfg.RANGO_CAUDAL_LPM
        qb = max(0.0, (fila["AMP_cau_betum_in"] - 4) / 16) * r["betun"]
        qs = max(0.0, (fila["AMP_cau_solucion_in"] - 4) / 16) * r["solucion"]
        produciendo = fila["ESTADO_operacion"] == "Produccion" and fila["AMP_cau_solucion_in"] < 20
        return {"relacion_betun": 100 * qb / (qb + qs) if produciendo and qb + qs > 0 else None,
                "relacion_objetivo": cfg.RELACION_OBJETIVO,
                "produccion_t": self.litros / 1000,
                "operacion_normal_pct": 100 * self.normales / self.minutos_marcha if self.minutos_marcha else None,
                "energia_kwh": self.kwh, "horas_marcha": self.minutos_marcha / 60}
