"""Simulador controlable de la planta (HU-17 a HU-19).

Reproduce el año 2026 del dataset minuto a minuto y publica cada lectura en AWS IoT Core, el
mismo camino que usaría el Edge Gateway de la planta real:

    simulador -> IoT Core -> Lambda de inferencia -> DynamoDB -> Lambda de persistencia -> RDS

Controles: pausar/reanudar, velocidad, ir a una fecha, fijar un modo de funcionamiento e
inyectar una falla encima de la operación real (escenarios del dashboard simulado de Franco).

Velocidad: la Lambda de inferencia procesa del orden de 2 lecturas por segundo, así que en las
velocidades altas se publica una lectura cada N minutos simulados (muestreo). El diagnóstico y
las alarmas siguen funcionando; la predicción es aproximada mientras se use el muestreo.

Al saltar de fecha (Ir a), el simulador:
  1. borra lo simulado desde esa fecha y precarga en RDS las 12 h anteriores (gráficos);
  2. reconstruye en S3 la ventana de 168 h y el estado de la bitácora que usa la Lambda;
  3. reinicia la Lambda para que descarte la ventana que tenía en memoria.

Recolección de resultados: el Learner Lab bloquea DynamoDB Streams (política de AWS Academy), así que
el propio servidor busca en DynamoDB el resultado de cada lectura que publicó y lo guarda en RDS. Solo
acepta el resultado si sus valores coinciden con los publicados, para no tomar uno antiguo del mismo minuto.
En una cuenta sin esa restricción se puede usar el camino DynamoDB Stream → Lambda qla-persistencia.

Modo de publicación (variable SIM_PUBLICAR):
  iot   (por defecto) publica en IoT Core.
  local guarda solo las lecturas en la base, sin modelos (para pruebas sin AWS).
"""
import datetime as dt
import io
import json
import logging
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, persistencia
from .db import cursor

log = logging.getLogger("simulador")

TOPIC = "planta/asfalto/molino/telemetria"
EQUIPO_IOT = "MOLINO_QLA_01"
LAMBDA_INFERENCIA = "qla-molino-inferencia"
TABLA_DYNAMO = "QLA_Molino_Telemetria"
ESPERA_MAXIMA_S = 120          # si la Lambda no deja el resultado en este tiempo, la lectura se descarta
SENSORES_CONTROL = ("TEM_son_betum_in", "PRE_dif_filtro_bar", "AMP_cau_solucion_in", "CAU_bomba_lpm")
ARCHIVO_DATASET = "Dataset_Molino_QLA_Realista.zip"
CLAVE_S3_DATASET = "despliegue/" + ARCHIVO_DATASET
CLAVE_S3_VENTANA = "ventana_activa/ultimas_168_horas.parquet"
CLAVE_S3_BITACORA = "bitacora/estado_equipos.json"
INICIO_POR_DEFECTO = "2026-09-01 08:40"          # periodo que ningún modelo vio, justo antes de producir
HORAS_PRECARGA = 12

# Las 29 variables que procesa la Lambda (mismo orden que inference_engine.SENSORES_29)
SENSORES_29 = [
    "TEM_son_betum_in", "RES_son_betum_in", "VOLT_son_betum_in", "AMP_son_betum_in", "AMP_cau_betum_in",
    "FRE_cau_betum_in", "AMP_eco_betum_dep", "EST_niv_betum_dep", "TEM_son_solucion_in", "RES_son_solucion_in",
    "AMP_son_solucion_in", "AMP_cau_solucion_in", "FRE_cau_solucion_in", "AMP_eco_solucion_dep",
    "TEM_son_emulsion_out", "RES_son_emulsion_out", "AMP_cau_emulsion_out", "FRE_cau_emulsion_out",
    "AMP_eco_emulsion_dep", "RPM_motor_molino", "FRE_vfd_motor_molino", "AMP_vfd_motor_molino",
    "TOR_vfd_motor_molino", "VIB_vel_motor_molino", "AMP_vib_motor_molino", "CAU_bomba_lpm",
    "PRE_dif_filtro_bar", "TEM_emulsion_molino_out", "PRE_intercambiador_bar",
]
ESTADOS_MARCHA = ("Produccion", "Limpieza")
SOLO_MARCHA = {"AMP_vfd_motor_molino", "TOR_vfd_motor_molino", "VIB_vel_motor_molino", "RPM_motor_molino",
               "CAU_bomba_lpm", "PRE_dif_filtro_bar", "TEM_emulsion_molino_out", "FRE_cau_emulsion_out"}
SOLO_PLASTOMERICO = {"PRE_intercambiador_bar"}

# paso: minutos simulados por publicación; intervalo: segundos entre publicaciones
VELOCIDADES = {
    "real": {"texto": "Tiempo real", "paso": 1, "intervalo": 60.0},
    "1m": {"texto": "1 minuto por segundo", "paso": 1, "intervalo": 1.0},
    "10m": {"texto": "10 minutos por segundo", "paso": 5, "intervalo": 0.5},
    "1h": {"texto": "1 hora por segundo", "paso": 30, "intervalo": 0.5},
}

MODOS = {
    "produccion_convencional": ("Producción convencional", "Produccion", "Convencional"),
    "produccion_plastomerico": ("Producción plastomérico", "Produccion", "Plastomerico"),
    "limpieza": ("Limpieza de línea", "Limpieza", "Convencional"),
    "preparacion": ("Preparación", "Preparacion", "Convencional"),
    "espera": ("En espera", "Espera", "Convencional"),
    "detenida": ("Planta detenida", "Detenida", "Ninguno"),
}


def _e(sensor, operacion, valor):
    return {"sensor": sensor, "operacion": operacion, "valor": valor}


# Escenarios de falla (mismos del dashboard simulado). Los efectos se aplican sobre los datos
# reproducidos; las señales del motor, bomba y filtro solo cambian con el molino en marcha.
ESCENARIOS = [
    {"clave": "caldera", "nombre": "Caldera perdiendo potencia", "categoria": "conocida", "evolucion": "gradual",
     "minutos": 4 * 1440, "equipo": "caldera",
     "descripcion": "El betún se enfría de a poco; al bajar de ~125 °C el motor entra en sobrecarga.",
     "efectos": [_e("TEM_son_betum_in", "sumar", -22), _e("AMP_vfd_motor_molino", "sumar", 22),
                 _e("TOR_vfd_motor_molino", "sumar", 22), _e("VIB_vel_motor_molino", "sumar", 1.0)]},
    {"clave": "filtro", "nombre": "Filtro obstruyéndose", "categoria": "conocida", "evolucion": "gradual",
     "minutos": 5 * 1440, "equipo": "filtro",
     "descripcion": "El filtro acumula sólidos: sube la presión diferencial y cae el caudal de la bomba.",
     "efectos": [_e("PRE_dif_filtro_bar", "sumar", 0.9), _e("CAU_bomba_lpm", "sumar", -22)]},
    {"clave": "radar", "nombre": "Radar ensuciándose", "categoria": "conocida", "evolucion": "gradual",
     "minutos": 7 * 1440, "equipo": "radar",
     "descripcion": "Costra de asfalto en la antena del radar de TK-101: el eco se debilita.",
     "efectos": [_e("AMP_eco_betum_dep", "sumar", -42)]},
    {"clave": "humedad_caudalimetro", "nombre": "Humedad en caudalímetro", "categoria": "conocida",
     "evolucion": "gradual", "minutos": 5 * 1440, "equipo": "caudalimetro",
     "descripcion": "Corriente de fuga creciente en el lazo de FT-201 antes del cortocircuito.",
     "efectos": [_e("AMP_cau_solucion_in", "sumar", 1.6)]},
    {"clave": "cortocircuito", "nombre": "Cortocircuito caudalímetro", "categoria": "conocida",
     "evolucion": "inmediata", "minutos": 1, "equipo": "caudalimetro",
     "descripcion": "El lazo de FT-201 se satura sobre 22 mA.",
     "efectos": [_e("AMP_cau_solucion_in", "fijar", 22.51)]},
    {"clave": "borneras", "nombre": "Borneras Pt100 corroídas", "categoria": "conocida", "evolucion": "gradual",
     "minutos": 6 * 1440, "equipo": "pt100",
     "descripcion": "Cae el voltaje de alimentación de la Pt100 del betún.",
     "efectos": [_e("VOLT_son_betum_in", "sumar", -1.6)]},
    {"clave": "pt100", "nombre": "Pt100 sin alimentación", "categoria": "conocida", "evolucion": "inmediata",
     "minutos": 1, "equipo": "pt100",
     "descripcion": "Pérdida total de los 24 V: temperatura, resistencia y lazo en cero.",
     "efectos": [_e("TEM_son_betum_in", "fijar", 0), _e("RES_son_betum_in", "fijar", 0),
                 _e("VOLT_son_betum_in", "fijar", 0), _e("AMP_son_betum_in", "fijar", 0)]},
    {"clave": "intercambiador", "nombre": "Intercambiador ensuciándose", "categoria": "conocida",
     "evolucion": "gradual", "minutos": 6 * 1440, "equipo": "intercambiador",
     "descripcion": "Depósitos en E-301: sube la presión en producción plastomérica.",
     "efectos": [_e("PRE_intercambiador_bar", "sumar", 1.3), _e("TEM_son_emulsion_out", "sumar", 8)]},
    {"clave": "rodamientos", "nombre": "Rodamientos desgastándose", "categoria": "conocida", "evolucion": "gradual",
     "minutos": 10 * 1440, "equipo": "rodamientos",
     "descripcion": "Desgaste mecánico: la vibración del molino sube durante días.",
     "efectos": [_e("VIB_vel_motor_molino", "sumar", 3.2), _e("AMP_vfd_motor_molino", "sumar", 4)]},
    {"clave": "cavitacion", "nombre": "Bomba cavitando", "categoria": "nueva", "evolucion": "gradual",
     "minutos": 360, "equipo": None,
     "descripcion": "Aire o vapor en la succión: el caudal cae y la frecuencia del Coriolis de emulsión sube.",
     "efectos": [_e("CAU_bomba_lpm", "multiplicar", 0.8), _e("FRE_cau_emulsion_out", "sumar", 18)]},
    {"clave": "sello", "nombre": "Sello mecánico con fuga", "categoria": "nueva", "evolucion": "gradual",
     "minutos": 1440, "equipo": None,
     "descripcion": "Roce en el sello del molino: sube la temperatura de salida y algo la vibración.",
     "efectos": [_e("TEM_emulsion_molino_out", "sumar", 12), _e("VIB_vel_motor_molino", "sumar", 0.8)]},
    {"clave": "solucion_fria", "nombre": "Solución fría", "categoria": "nueva", "evolucion": "gradual",
     "minutos": 720, "equipo": None,
     "descripcion": "Falla del calefactor de la solución jabonosa: baja a 22 °C.",
     "efectos": [_e("TEM_son_solucion_in", "sumar", -14)]},
    {"clave": "variador", "nombre": "Variador inestable", "categoria": "nueva", "evolucion": "inmediata",
     "minutos": 1, "equipo": None,
     "descripcion": "El variador del molino oscila: baja la velocidad y la frecuencia.",
     "efectos": [_e("RPM_motor_molino", "multiplicar", 0.85), _e("FRE_vfd_motor_molino", "multiplicar", 0.85)]},
]
_ESC = {e["clave"]: e for e in ESCENARIOS}

# Claves del archivo estado_equipos.json que lee la Lambda (igual que estado_equipos.json del repo)
CLAVES_BITACORA = {"filtro": "filtro", "radar": "radar", "caldera": "caldera", "intercambiador": "intercambiador",
                   "caudalimetro": "caudalimetro", "pt100": "pt100", "rodamientos": "rodamientos"}
CLAVE_LARGA = {"rodamientos": "ultima_mantencion_cojinetes"}


class SimuladorNoDisponible(Exception):
    pass


class Simulador:
    def __init__(self):
        self._lock = threading.RLock()
        self._hilo = None
        self.df = None
        self.pos = 0
        self.reloj = None                    # instante simulado (pd.Timestamp UTC)
        self.velocidad = "1m"
        self.saltar_paradas = True           # con el calendario real, las paradas pasan a 1 hora por segundo
        self.corriendo = False
        self.preparando = None               # texto mientras se prepara un salto de fecha
        self.modo = None
        self.pools, self.pool_pos = {}, {}
        self.escenario, self.esc_inicio = None, None
        self.contador = 0                    # minutos simulados desde que partió
        self.etiqueta = None
        self.publicados = 0
        self.errores_seguidos = 0
        self.ultimo_error = None
        self.aviso = None
        self.episodios = []
        self.bitacora_eventos = []           # instantes de intervenciones (para refrescar estado_equipos.json)
        self._prox_bitacora = None
        self.publicar_modo = config.SIM_PUBLICAR
        self._preparado = False              # S3 y la Lambda ya están alineados con la fecha simulada
        self._aws = {}
        self._pendientes = {}                # epoch -> (lectura publicada, instante de publicación)
        self._hilo_recolector = None
        self.recolectados = 0
        self.descartados = 0

    # ------------------------------------------------------------------ AWS
    def _cliente(self, nombre):
        if nombre not in self._aws:
            import boto3
            if nombre == "iot-data":
                ep = config.IOT_ENDPOINT or boto3.client("iot", region_name=config.AWS_REGION).describe_endpoint(
                    endpointType="iot:Data-ATS")["endpointAddress"]
                ep = ep if ep.startswith("https://") else "https://" + ep
                self._aws[nombre] = boto3.client("iot-data", region_name=config.AWS_REGION, endpoint_url=ep)
            else:
                self._aws[nombre] = boto3.client(nombre, region_name=config.AWS_REGION)
        return self._aws[nombre]

    def _bucket(self) -> str:
        if config.SIM_BUCKET:
            return config.SIM_BUCKET
        if "bucket" not in self._aws:
            cfg = self._cliente("lambda").get_function_configuration(FunctionName=LAMBDA_INFERENCIA)
            self._aws["bucket"] = cfg.get("Environment", {}).get("Variables", {}).get("S3_BUCKET")
        if not self._aws["bucket"]:
            raise SimuladorNoDisponible("No se encontró el bucket S3 de la Lambda de inferencia")
        return self._aws["bucket"]

    # ------------------------------------------------------------------ datos
    def _ruta_dataset(self) -> Path:
        candidatos = [Path(config.SIM_DATASET)] if config.SIM_DATASET else []
        candidatos += [config.RAIZ.parent / "Dataset Simulado" / ARCHIVO_DATASET,
                       Path(tempfile.gettempdir()) / "qla_datos" / ARCHIVO_DATASET]
        for c in candidatos:
            if c.exists():
                return c
        destino = candidatos[-1]
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._cliente("s3").download_file(self._bucket(), CLAVE_S3_DATASET, str(destino))
        except Exception as e:
            raise SimuladorNoDisponible(f"No se encontró el dataset ({ARCHIVO_DATASET}) ni en S3: {e}") from None
        return destino

    def _cargar(self):
        if self.df is not None:
            return
        ruta = self._ruta_dataset()
        log.info("Cargando dataset %s", ruta)
        df = pd.read_csv(ruta)
        num = [c for c in df.columns if c not in ("timestamp", "ESTADO_operacion", "TIPO_asfalto",
                                                     "LABEL_Estado_Planta")]
        df[num] = df[num].astype("float32")
        ts = pd.to_datetime(df["timestamp"]).dt.tz_localize(config.ZONA_HORARIA, ambiguous="NaT",
                                                            nonexistent="shift_forward")
        df["timestamp"] = ts.dt.tz_convert("UTC")
        df = df[df["timestamp"].notna()].reset_index(drop=True)
        for c in ("ESTADO_operacion", "TIPO_asfalto", "LABEL_Estado_Planta"):
            df[c] = df[c].astype("category")
        self.df = df
        # Minutos normales del primer semestre por modo, para fijar un modo de funcionamiento
        sano = df[(df["LABEL_Estado_Planta"] == "Normal") & (df["timestamp"] < pd.Timestamp("2026-07-01", tz="UTC"))]
        for clave, (_, est, tipo) in MODOS.items():
            self.pools[clave] = sano[(sano["ESTADO_operacion"] == est) & (sano["TIPO_asfalto"] == tipo)
                                     ].reset_index(drop=True)
            self.pool_pos[clave] = 0
        # Episodios reales de falla, para "Ir a 3 días antes de..."
        etq = df["LABEL_Estado_Planta"].astype(str)
        nuevo = (etq != "Normal") & (etq != etq.shift())
        ev = df.loc[nuevo, ["timestamp"]].assign(estado=etq[nuevo])
        ev = ev[ev["timestamp"].diff().isna() | (ev["timestamp"].diff() > pd.Timedelta(hours=24))
                | (ev["estado"] != ev["estado"].shift())]
        self.episodios = [{"falla": e, "inicio": t.isoformat()} for t, e in zip(ev["timestamp"], ev["estado"])]
        self.pos = int(np.searchsorted(df["timestamp"].values,
                                       pd.Timestamp(INICIO_POR_DEFECTO, tz=config.ZONA_HORARIA).tz_convert("UTC")
                                       .to_datetime64()))
        self.reloj = df["timestamp"].iloc[self.pos]

    # ------------------------------------------------------------------ bloques de datos
    def _siguiente(self, n: int) -> pd.DataFrame:
        if self.modo:
            pool = self.pools[self.modo]
            i = self.pool_pos[self.modo]
            idx = np.arange(i, i + n) % len(pool)
            self.pool_pos[self.modo] = int((i + n) % len(pool))
            b = pool.iloc[idx].copy()
            b["timestamp"] = self.reloj + pd.to_timedelta(np.arange(1, n + 1), unit="min")
        else:
            fin = min(self.pos + n, len(self.df))
            b = self.df.iloc[self.pos:fin].copy()
            self.pos = fin if fin < len(self.df) else 0
        num = b.select_dtypes("float32").columns
        b[num] = b[num].astype("float64")
        if self.escenario:
            self._aplicar(b, self.contador + np.arange(len(b)) - self.esc_inicio)
            b["LABEL_Estado_Planta"] = np.where(b["LABEL_Estado_Planta"].astype(str) == "Normal",
                                                "Simulado: " + self.escenario["nombre"],
                                                b["LABEL_Estado_Planta"].astype(str))
        self.contador += len(b)
        self.reloj = b["timestamp"].iloc[-1]
        return b

    def _aplicar(self, b: pd.DataFrame, minutos: np.ndarray) -> None:
        e = self.escenario
        prog = np.ones(len(b)) if e["evolucion"] == "inmediata" else np.clip(minutos / e["minutos"], 0, 1)
        est = b["ESTADO_operacion"].astype(str).values
        marcha = np.isin(est, ESTADOS_MARCHA)
        plasto_prod = (est == "Produccion") & (b["TIPO_asfalto"].astype(str).values == "Plastomerico")
        for ef in e["efectos"]:
            s, op, val = ef["sensor"], ef["operacion"], ef["valor"]
            if s not in b:
                continue
            aplica = plasto_prod if s in SOLO_PLASTOMERICO else (marcha if s in SOLO_MARCHA else np.ones(len(b), bool))
            x = b[s].values.astype(float)
            objetivo = {"fijar": np.full(len(b), val), "sumar": x + val, "multiplicar": x * val}[op]
            b[s] = np.where(aplica, x + (objetivo - x) * prog, x)
        # Variables derivadas, para que el escenario sea físicamente coherente
        tb = b["TEM_son_betum_in"]
        ok = b["VOLT_son_betum_in"] > 1
        b.loc[ok, "RES_son_betum_in"] = 100 * (1 + 0.00385 * tb[ok])
        b.loc[ok, "AMP_son_betum_in"] = 4 + 16 * tb[ok] / 250
        b["RES_son_solucion_in"] = 100 * (1 + 0.00385 * b["TEM_son_solucion_in"])
        b["AMP_son_solucion_in"] = 4 + 16 * b["TEM_son_solucion_in"] / 100
        b["EST_niv_betum_dep"] = (b["AMP_eco_betum_dep"] < 23).astype(float)
        b["AMP_vib_motor_molino"] = 4 + 0.64 * b["VIB_vel_motor_molino"]

    @staticmethod
    def _lectura(fila: pd.Series) -> dict:
        lect = {k: round(float(v), 4) for k, v in fila.items()
                if k not in ("timestamp", "ESTADO_operacion", "TIPO_asfalto", "LABEL_Estado_Planta")}
        lect["ESTADO_operacion"] = str(fila["ESTADO_operacion"])
        lect["TIPO_asfalto"] = str(fila["TIPO_asfalto"])
        return lect

    # ------------------------------------------------------------------ publicación
    def _publicar(self, fila: pd.Series) -> None:
        lect = self._lectura(fila)
        epoch = int(fila["timestamp"].timestamp())
        if self.publicar_modo == "iot":
            payload = {"equipo_id": EQUIPO_IOT, "timestamp": epoch, "origen": "simulador",
                       "lectura_actual": {k: lect[k] for k in SENSORES_29 + ["ESTADO_operacion", "TIPO_asfalto"]
                                          if k in lect}}
            self._cliente("iot-data").publish(topic=TOPIC, qos=1, payload=json.dumps(payload))
            with self._lock:
                self._pendientes[epoch] = (payload["lectura_actual"], time.monotonic())
            extras = {k: v for k, v in lect.items() if k not in SENSORES_29 and k not in
                      ("ESTADO_operacion", "TIPO_asfalto")}
            with cursor() as cur:
                _guardar_extras(cur, fila["timestamp"].to_pydatetime(), extras)
        else:   # local: sin modelos, solo lecturas, estado y reglas fijas
            with cursor() as cur:
                persistencia.guardar_registro(cur, {"timestamp": epoch, "lectura": lect}, "simulado",
                                              config.EQUIPO_POR_DEFECTO)
        self.publicados += 1

    # ------------------------------------------------------------------ ciclo
    def _ciclo(self):
        while True:
            with self._lock:
                activo = self.corriendo and not self.preparando
                vel = dict(VELOCIDADES[self.velocidad])
                if (activo and self.saltar_paradas and not self.modo and self.df is not None
                        and str(self.df["ESTADO_operacion"].iat[self.pos]) not in ESTADOS_MARCHA):
                    # Planta detenida, en espera o en preparación: avanza 1 hora por segundo
                    vel["paso"] = max(vel["paso"], 30)
                    vel["intervalo"] = min(vel["intervalo"], 0.5)
            if not activo:
                time.sleep(0.2)
                continue
            t0 = time.monotonic()
            try:
                with self._lock:
                    bloque = self._siguiente(vel["paso"])
                    fila = bloque.iloc[-1]
                    self.etiqueta = str(fila["LABEL_Estado_Planta"])
                self._publicar(fila)
                self._refrescar_bitacora_si_corresponde()
                self.errores_seguidos, self.ultimo_error = 0, None
            except Exception as e:      # se informa en la pantalla y se reintenta
                self.errores_seguidos += 1
                self.ultimo_error = f"{type(e).__name__}: {e}"[:300]
                log.warning("Simulador: %s", self.ultimo_error)
                if self.errores_seguidos >= 5:
                    with self._lock:
                        self.corriendo = False
                        self.aviso = "Simulación pausada: 5 errores seguidos al publicar. " + self.ultimo_error
            time.sleep(max(0.0, vel["intervalo"] - (time.monotonic() - t0)))

    def _asegurar(self):
        with self._lock:
            self._cargar()
            if self._hilo is None or not self._hilo.is_alive():
                self._hilo = threading.Thread(target=self._ciclo, name="simulador", daemon=True)
                self._hilo.start()
            if self.publicar_modo == "iot" and (self._hilo_recolector is None or not self._hilo_recolector.is_alive()):
                self._hilo_recolector = threading.Thread(target=self._recolector, name="recolector", daemon=True)
                self._hilo_recolector.start()

    # ------------------------------------------------------------------ resultados desde DynamoDB
    def _recolector(self):
        """Cada segundo busca en DynamoDB los resultados de las lecturas publicadas y los guarda en RDS,
        en orden de tiempo (las alarmas 3 de 5 necesitan el orden)."""
        while True:
            time.sleep(1.0)
            with self._lock:
                pendientes = sorted(self._pendientes.items())
            if not pendientes:
                continue
            try:
                encontrados = self._buscar_en_dynamo([e for e, _ in pendientes[:100]])
                ahora = time.monotonic()
                listos = []
                for epoch, (publicada, t_pub) in pendientes[:100]:
                    item = encontrados.get(epoch)
                    if item is not None and _coincide(item.get("lectura") or {}, publicada):
                        listos.append((epoch, item))
                    elif ahora - t_pub > ESPERA_MAXIMA_S:
                        listos.append((epoch, None))      # no llegó a tiempo: se descarta
                    else:
                        break                              # se respeta el orden: espera a la más antigua
                if not listos:
                    continue
                with cursor() as cur:
                    for epoch, item in listos:
                        if item is not None:
                            persistencia.guardar_registro(cur, item, "simulado", config.EQUIPO_POR_DEFECTO)
                with self._lock:
                    for epoch, item in listos:
                        self._pendientes.pop(epoch, None)
                        if item is None:
                            self.descartados += 1
                        else:
                            self.recolectados += 1
            except Exception as e:
                self.ultimo_error = f"Al leer resultados de DynamoDB: {type(e).__name__}: {e}"[:300]
                log.warning("Recolector: %s", self.ultimo_error)
                time.sleep(4)

    def _buscar_en_dynamo(self, epochs: list) -> dict:
        from decimal import Decimal
        if "dynamo" not in self._aws:
            import boto3
            self._aws["dynamo"] = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        res = self._aws["dynamo"].batch_get_item(RequestItems={TABLA_DYNAMO: {
            "Keys": [{"equipo_id": EQUIPO_IOT, "timestamp": e} for e in epochs], "ConsistentRead": True}})
        items = res.get("Responses", {}).get(TABLA_DYNAMO, [])

        def plano(v):
            if isinstance(v, Decimal):
                return int(v) if v == v.to_integral_value() else float(v)
            if isinstance(v, dict):
                return {k: plano(x) for k, x in v.items()}
            if isinstance(v, list):
                return [plano(x) for x in v]
            return v
        return {int(i["timestamp"]): plano(i) for i in items}

    # ------------------------------------------------------------------ bitácora y ventana de la Lambda
    def _bitacora_en(self, cur, t: dt.datetime) -> dict:
        from .rutas.pantallas import EQUIPOS, SQL_INTERVENCIONES   # mismo criterio que la pantalla de Mantenimiento
        eq = persistencia._catalogos(cur)["equipos"][config.EQUIPO_POR_DEFECTO]
        res = {}
        for e in EQUIPOS:
            cur.execute("SELECT max(m.fecha_inicio) AS f" + SQL_INTERVENCIONES, (eq, "simulado", t, e["falla"]))
            f = cur.fetchone()["f"]
            if f:
                iso = f.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                res[e["clave"]] = iso
                res[CLAVE_LARGA.get(e["clave"], "ultima_mantencion_" + e["clave"])] = iso
        return res

    def _escribir_bitacora(self, t: dt.datetime) -> None:
        with cursor() as cur:
            estado = self._bitacora_en(cur, t)
            eq = persistencia._catalogos(cur)["equipos"][config.EQUIPO_POR_DEFECTO]
            cur.execute("""SELECT fecha_inicio FROM mantpred.mantenimientos
                           WHERE equipo_id = %s AND fuente = 'simulado' AND fecha_inicio > %s
                           ORDER BY fecha_inicio LIMIT 1""", (eq, t))
            prox = cur.fetchone()
        self._prox_bitacora = prox["fecha_inicio"] if prox else None
        if self.publicar_modo == "iot":
            self._cliente("s3").put_object(Bucket=self._bucket(), Key=CLAVE_S3_BITACORA,
                                           Body=json.dumps({EQUIPO_IOT: estado}, indent=2).encode(),
                                           ContentType="application/json")

    def _refrescar_bitacora_si_corresponde(self):
        if self._prox_bitacora and self.reloj.to_pydatetime() >= self._prox_bitacora:
            self._escribir_bitacora(self.reloj.to_pydatetime())

    def _escribir_ventana(self, t: pd.Timestamp) -> int:
        """Ventana de 168 h con el mismo formato que mantiene la Lambda (31 variables + estado)."""
        d = self.df[(self.df["timestamp"] >= t - pd.Timedelta(hours=168)) & (self.df["timestamp"] < t)]
        v = pd.DataFrame({"timestamp": (d["timestamp"].astype("int64") // 10**9).astype("int64")})
        v["ESTADO_operacion"] = d["ESTADO_operacion"].astype(str).values
        v["TIPO_asfalto"] = d["TIPO_asfalto"].astype(str).values
        v["es_plastomerico"] = (v["TIPO_asfalto"] == "Plastomerico").astype(int)
        v["en_limpieza"] = (v["ESTADO_operacion"] == "Limpieza").astype(int)
        for s in SENSORES_29:
            v[s] = d[s].astype("float64").values
        buf = io.BytesIO()
        v.to_parquet(buf, index=False)
        self._cliente("s3").put_object(Bucket=self._bucket(), Key=CLAVE_S3_VENTANA, Body=buf.getvalue())
        return len(v)

    def _reiniciar_lambda(self) -> None:
        """Cambia una variable de entorno: AWS reemplaza las instancias en caliente, que así
        vuelven a leer la ventana y la bitácora desde S3."""
        lam = self._cliente("lambda")
        cfg = lam.get_function_configuration(FunctionName=LAMBDA_INFERENCIA)
        variables = dict(cfg.get("Environment", {}).get("Variables", {}))
        variables["SIM_REINICIO"] = str(int(time.time()))
        lam.update_function_configuration(FunctionName=LAMBDA_INFERENCIA, Environment={"Variables": variables})
        lam.get_waiter("function_updated").wait(FunctionName=LAMBDA_INFERENCIA,
                                                WaiterConfig={"Delay": 2, "MaxAttempts": 60})

    def _preparar(self, t: pd.Timestamp):
        """Deja RDS, S3 y la Lambda consistentes con el instante t (se ejecuta en segundo plano)."""
        try:
            tp = t.to_pydatetime()
            with cursor() as cur:
                eq = persistencia._catalogos(cur)["equipos"][config.EQUIPO_POR_DEFECTO]
                persistencia.reiniciar_desde(cur, eq, "simulado", tp)
            self.preparando = "Cargando las 12 h previas en la base"
            previo = self.df[(self.df["timestamp"] >= t - pd.Timedelta(hours=HORAS_PRECARGA))
                             & (self.df["timestamp"] < t)]
            with cursor() as cur:
                for _, fila in previo.iterrows():
                    persistencia.guardar_registro(cur, {"timestamp": int(fila["timestamp"].timestamp()),
                                                        "lectura": self._lectura(fila)},
                                                  "simulado", config.EQUIPO_POR_DEFECTO)
            self.preparando = "Actualizando la bitácora y la ventana de 168 h de la Lambda"
            self._escribir_bitacora(tp)
            if self.publicar_modo == "iot":
                self._escribir_ventana(t)
                self.preparando = "Reiniciando la Lambda de inferencia"
                try:
                    self._reiniciar_lambda()
                except Exception as e:
                    self.aviso = ("No se pudo reiniciar la Lambda de inferencia; la predicción puede tardar en "
                                  f"ajustarse a la nueva fecha ({type(e).__name__})")
            self.ultimo_error = None
        except Exception as e:
            self.ultimo_error = f"Al preparar la fecha: {type(e).__name__}: {e}"[:300]
            log.exception("Simulador: error al preparar")
        finally:
            self.preparando = None

    def _saltar(self, t: pd.Timestamp, motivo: str):
        with self._lock:
            self._pendientes.clear()        # lo publicado antes del salto ya no corresponde
        self.preparando = motivo
        self._preparado = True
        threading.Thread(target=self._preparar, args=(t,), daemon=True).start()

    # ------------------------------------------------------------------ API pública
    def estado(self) -> dict:
        e = self.escenario
        out = {"disponible": self.df is not None, "corriendo": self.corriendo, "preparando": self.preparando,
               "velocidad": self.velocidad, "modo": self.modo, "saltar_paradas": self.saltar_paradas, "tiempo": self.reloj.isoformat() if self.reloj is not None else None,
               "etiqueta_real": self.etiqueta, "publicacion": self.publicar_modo, "publicados": self.publicados,
               "error": self.ultimo_error, "aviso": self.aviso,
               "recolectados": self.recolectados, "pendientes": len(self._pendientes),
               "descartados": self.descartados,
               "escenario": None}
        if e:
            trans = self.contador - self.esc_inicio
            out["escenario"] = {"clave": e["clave"], "nombre": e["nombre"],
                                "progreso": 1.0 if e["evolucion"] == "inmediata" else float(min(1, trans / e["minutos"]))}
        return out

    def opciones(self) -> dict:
        self._asegurar()
        nombres = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                   "octubre", "noviembre", "diciembre")
        meses = [{"etiqueta": f"1 de {n}", "fecha": f"2026-{i:02d}-01T08:40"} for i, n in enumerate(nombres, 1)]
        antes = []
        for ep in self.episodios:
            t = pd.Timestamp(ep["inicio"])
            if t >= pd.Timestamp("2026-07-01", tz="UTC"):
                f = (t - pd.Timedelta(days=3)).tz_convert(config.ZONA_HORARIA)
                antes.append({"etiqueta": f"3 días antes de {ep['falla']} ({t.tz_convert(config.ZONA_HORARIA):%d-%m %H:%M})",
                              "fecha": f.strftime("%Y-%m-%dT%H:%M")})
        return {"velocidades": [{"clave": k, "texto": v["texto"]} for k, v in VELOCIDADES.items()],
                "modos": [{"clave": k, "texto": v[0]} for k, v in MODOS.items()],
                "escenarios": [{k: e[k] for k in ("clave", "nombre", "categoria", "descripcion", "evolucion", "minutos")}
                               for e in ESCENARIOS],
                "ir_a": {"meses": meses, "antes_de_falla": antes}}

    def controlar(self, accion: str, valor: str | None = None) -> dict:
        self._asegurar()
        with self._lock:
            if self.preparando and accion in ("ir_a", "modo", "escenario"):
                raise ValueError("Espere: la simulación se está preparando (" + self.preparando + ")")
            self.aviso = None
            if accion == "iniciar":
                if not self._preparado:
                    # primer inicio: deja S3 y la Lambda alineados con la fecha simulada
                    self._saltar(self.reloj, "Preparando la fecha inicial")
                self.corriendo = True
                self.errores_seguidos = 0
            elif accion == "pausar":
                self.corriendo = False
            elif accion == "saltar_paradas":
                self.saltar_paradas = valor in ("1", "true", "si", "sí")
            elif accion == "velocidad":
                if valor not in VELOCIDADES:
                    raise ValueError("Velocidad desconocida")
                self.velocidad = valor
            elif accion == "ir_a":
                try:
                    t = pd.Timestamp(valor).tz_localize(config.ZONA_HORARIA).tz_convert("UTC")
                except Exception:
                    raise ValueError("Fecha no válida (use AAAA-MM-DDTHH:MM)") from None
                self.modo, self.escenario, self.esc_inicio, self.etiqueta = None, None, None, None
                self.pos = int(np.clip(np.searchsorted(self.df["timestamp"].values, t.to_datetime64()),
                                       0, len(self.df) - 1))
                self.reloj = self.df["timestamp"].iloc[self.pos]
                self._saltar(self.reloj, "Preparando la nueva fecha")
            elif accion == "modo":
                if valor and valor not in MODOS:
                    raise ValueError("Modo de funcionamiento desconocido")
                if valor:
                    self.modo = valor
                else:   # vuelve al calendario real en la misma fecha
                    self.modo = None
                    self.pos = int(np.clip(np.searchsorted(self.df["timestamp"].values, self.reloj.to_datetime64()),
                                           0, len(self.df) - 1))
            elif accion == "escenario":
                if valor and valor not in _ESC:
                    raise ValueError("Escenario desconocido")
                self.escenario = _ESC[valor] if valor else None
                self.esc_inicio = self.contador if valor else None
            else:
                raise ValueError("Acción desconocida")
        return self.estado()


def _coincide(guardada: dict, publicada: dict) -> bool:
    """El resultado de DynamoDB corresponde a esta lectura si sus sensores de control son iguales."""
    for s in SENSORES_CONTROL:
        a, b = guardada.get(s), publicada.get(s)
        if a is None or b is None:
            continue
        if abs(float(a) - float(b)) > 1e-3:
            return False
    return True


def _guardar_extras(cur, t: dt.datetime, extras: dict) -> None:
    """Sensores que la Lambda no usa (niveles de estanques, válvulas): se guardan directo."""
    cat = persistencia._catalogos(cur)["sensores"]
    ids, vals = [], []
    for tag, v in extras.items():
        if tag in cat and v is not None and np.isfinite(v):
            ids.append(cat[tag])
            vals.append(float(v))
    if ids:
        cur.execute("""INSERT INTO mantpred.lecturas (sensor_id, ts, valor, fuente)
                       SELECT unnest(%s::int[]), %s, unnest(%s::numeric[]), 'simulado'
                       ON CONFLICT DO NOTHING""", (ids, t.replace(second=0, microsecond=0), vals))


simulador = Simulador()
