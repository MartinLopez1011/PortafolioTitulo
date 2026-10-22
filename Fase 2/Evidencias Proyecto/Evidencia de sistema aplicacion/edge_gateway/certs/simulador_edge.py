"""Simulador Edge Gateway con validación Pydantic (31 variables) y cola local Store-and-Forward (SQLite WAL)."""
from pathlib import Path
import json
import os
import sqlite3
import time
import pandas as pd
import requests
from pydantic import BaseModel

LAMBDA_URL = os.environ.get("LAMBDA_URL", "https://pczeontvrrhrvqjlaluqdvrokm0ysgdo.lambda-url.us-east-1.on.aws/")
DB_BUFFER_PATH = Path(__file__).resolve().parent / "edge_store_and_forward.db"


class Lectura31Molino(BaseModel):
    """Contrato canónico validado de las 31 variables de entrada (29 sensores float + 2 binarias int)."""
    ESTADO_operacion: str = "Produccion"
    TIPO_asfalto: str = "Convencional"
    TEM_son_betum_in: float = 134.7
    RES_son_betum_in: float = 151.86
    VOLT_son_betum_in: float = 23.76
    AMP_son_betum_in: float = 12.62
    AMP_cau_betum_in: float = 12.3
    FRE_cau_betum_in: float = 249.5
    AMP_eco_betum_dep: float = 52.33
    EST_niv_betum_dep: float = 0.0
    TEM_son_solucion_in: float = 36.4
    RES_son_solucion_in: float = 114.01
    AMP_son_solucion_in: float = 9.82
    AMP_cau_solucion_in: float = 13.31
    FRE_cau_solucion_in: float = 400.0
    AMP_eco_solucion_dep: float = 70.0
    TEM_son_emulsion_out: float = 72.5
    RES_son_emulsion_out: float = 127.91
    AMP_cau_emulsion_out: float = 14.44
    FRE_cau_emulsion_out: float = 322.7
    AMP_eco_emulsion_dep: float = 60.0
    RPM_motor_molino: float = 2898.0
    FRE_vfd_motor_molino: float = 50.0
    AMP_vfd_motor_molino: float = 105.7
    TOR_vfd_motor_molino: float = 71.7
    VIB_vel_motor_molino: float = 2.47
    AMP_vib_motor_molino: float = 5.58
    CAU_bomba_lpm: float = 180.6
    PRE_dif_filtro_bar: float = 0.42
    TEM_emulsion_molino_out: float = 73.5
    PRE_intercambiador_bar: float = 0.0
    es_plastomerico: int = 0
    en_limpieza: int = 0


class ColaStoreAndForward:
    """Cola transaccional SQLite en modo WAL para resiliencia ante cortes de red en planta (OT)."""

    def __init__(self, db_path: Path = DB_BUFFER_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS buffer_telemetria (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )"""
            )
            conn.commit()

    def encolar(self, payload: dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO buffer_telemetria (timestamp, payload_json) VALUES (?, ?)",
                (int(payload.get("timestamp", time.time())), json.dumps(payload)),
            )
            conn.commit()

    def drenar(self, enviar_fn, max_lote: int = 25) -> int:
        enviados = 0
        with sqlite3.connect(self.db_path) as conn:
            filas = conn.execute(
                "SELECT id, payload_json FROM buffer_telemetria ORDER BY id ASC LIMIT ?",
                (max_lote,),
            ).fetchall()
            for msg_id, raw_json in filas:
                try:
                    if enviar_fn(json.loads(raw_json)):
                        conn.execute("DELETE FROM buffer_telemetria WHERE id = ?", (msg_id,))
                        conn.commit()
                        enviados += 1
                    else:
                        break
                except Exception:
                    break
        return enviados


def construir_payload_canonico(datos_crudos: dict, equipo_id: str = "MOLINO_QLA_01", ts: int | None = None) -> dict:
    """Valida las 31 variables con Pydantic y construye un payload híbrido (plano + lectura_actual)."""
    base = datos_crudos.get("lectura_actual", datos_crudos) if isinstance(datos_crudos, dict) else {}
    copia = dict(base)
    tipo_asf = str(copia.get("TIPO_asfalto", "Convencional"))
    estado_op = str(copia.get("ESTADO_operacion", "Produccion"))
    copia["es_plastomerico"] = int(tipo_asf.lower().startswith("plasto") or bool(copia.get("es_plastomerico", 0)))
    copia["en_limpieza"] = int(estado_op.lower() == "limpieza" or bool(copia.get("en_limpieza", 0)))

    validado = Lectura31Molino(**copia).model_dump()
    timestamp = int(ts if ts is not None else datos_crudos.get("timestamp", time.time()))
    return {
        "equipo_id": equipo_id,
        "timestamp": timestamp,
        **validado,
        "lectura_actual": validado,
    }


def _enviar_http(payload: dict) -> bool:
    resp = requests.post(LAMBDA_URL, json=payload, timeout=15)
    return resp.status_code == 200


def iniciar_simulacion(ruta_csv: str, intervalo_seg: int = 3, max_envios: int = 20):
    print(f"Cargando datos de planta desde: {ruta_csv}")
    cola = ColaStoreAndForward()
    df = pd.read_csv(ruta_csv)

    df_activo = df[df["ESTADO_operacion"].isin(["Produccion", "Limpieza"])].tail(max_envios)

    for _, row in df_activo.iterrows():
        payload = construir_payload_canonico(row.to_dict())

        try:
            cola.drenar(_enviar_http)
            inicio = time.time()
            resp = requests.post(LAMBDA_URL, json=payload, timeout=15)
            latencia = round((time.time() - inicio) * 1000, 1)

            if resp.status_code == 200:
                data = resp.json()["resultado"]
                diag = data["diagnostico"]["falla"]
                mse = data["vigilancia_autoencoder"]["mse"]
                alerta_ae = data["vigilancia_autoencoder"]["alerta_anomalia_nueva"]
                print(
                    f"[OK {latencia}ms] Estado: {data['estado_operacion']} "
                    f"| Diagnóstico: {diag} | MSE AE: {mse} (Alerta: {alerta_ae})"
                )
            else:
                print(f"[ERROR {resp.status_code}] Encolando en SQLite Store-and-Forward...")
                cola.encolar(payload)
        except Exception as e:
            print(f"[FALLO CONEXIÓN] {e} -> Guardado en cola local SQLite WAL")
            cola.encolar(payload)

        time.sleep(intervalo_seg)


if __name__ == "__main__":
    cola_local = ColaStoreAndForward()
    ruta_test = Path(__file__).resolve().parent.parent.parent / "lambda_inferencia" / "app" / "test_payload.json"
    with open(ruta_test, "r", encoding="utf-8") as f:
        muestra = json.load(f)

    print("Enviando telemetría desde Edge Gateway hacia AWS Lambda...")
    for i in range(5):
        paquete = construir_payload_canonico(muestra, ts=int(time.time()))
        try:
            cola_local.drenar(_enviar_http)
            r = requests.post(LAMBDA_URL, json=paquete, timeout=15)
            print(f"Envío #{i+1} -> Status {r.status_code} | Diagnóstico: {r.json()['resultado']['diagnostico']['falla']}")
        except Exception as exc:
            print(f"Envío #{i+1} sin red ({exc}) -> Encolado en Store-and-Forward.")
            cola_local.encolar(paquete)
        time.sleep(2)
