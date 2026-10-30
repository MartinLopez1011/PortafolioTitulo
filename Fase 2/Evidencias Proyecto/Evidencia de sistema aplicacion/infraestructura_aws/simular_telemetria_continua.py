"""Simulador de flujo continuo de telemetría para el Molino Coloidal MC-01 (QLA).

Publica lecturas periódicas a AWS IoT Core en el topic 'planta/asfalto/molino/telemetria'
con validación Pydantic de las 31 variables canónicas y cola local SQLite WAL (Store-and-Forward).
Alimenta simultáneamente:
  1. Cold Path: Firehose -> S3 Parquet -> Athena (campos planos en raíz compatibles con glue_table.json)
  2. ML Path: IoT Rule -> Lambda Inferencia -> DynamoDB y alertas
  3. Hot Path: AWS IoT Core WebSockets -> Dashboard Frontend en vivo
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import random
import sqlite3
import time
import boto3
from pydantic import BaseModel

REGION = os.environ.get("AWS_REGION", "us-east-1")


def _resolver_iot_endpoint() -> str:
    ep = os.environ.get("IOT_ENDPOINT", "").strip()
    if ep:
        return ep if ep.startswith("https://") else f"https://{ep}"
    try:
        addr = boto3.client("iot", region_name=REGION).describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
        return f"https://{addr}"
    except Exception:
        return "https://a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com"


IOT_ENDPOINT = _resolver_iot_endpoint()
TOPIC_TELEMETRIA = "planta/asfalto/molino/telemetria"
DB_BUFFER_PATH = Path(__file__).resolve().parent / "iot_store_and_forward.db"

MODOS_SIMULACION = (
    "normal",
    "overload_vfd",
    "clogged_filter",
    "radar_dirty",
    "short_circuit",
    "pt100_drift",
    "exchanger_fouling",
    "bearing_wear",
)


class Lectura31Molino(BaseModel):
    """Esquema validado de las 31 variables de entrada (29 sensores float + 2 binarias int)."""
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
    """Buffer local SQLite WAL ante desconexiones hacia AWS IoT Core."""

    def __init__(self, db_path: Path = DB_BUFFER_PATH):
        self.db_path = Path(db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS cola_mqtt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )"""
            )
            conn.commit()

    def encolar(self, payload: dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO cola_mqtt (timestamp, payload_json) VALUES (?, ?)",
                (int(payload.get("timestamp", time.time())), json.dumps(payload)),
            )
            conn.commit()

    def drenar(self, iot_client, topic: str, max_lote: int = 20) -> int:
        reenviados = 0
        with sqlite3.connect(self.db_path) as conn:
            filas = conn.execute("SELECT id, payload_json FROM cola_mqtt ORDER BY id ASC LIMIT ?", (max_lote,)).fetchall()
            for row_id, raw_json in filas:
                try:
                    iot_client.publish(topic=topic, qos=1, payload=raw_json)
                    conn.execute("DELETE FROM cola_mqtt WHERE id = ?", (row_id,))
                    conn.commit()
                    reenviados += 1
                except Exception:
                    break
        return reenviados


def generar_lectura(ciclo: int, simular_anomalia: bool = False, modo: str = "normal") -> dict:
    """Genera valores de proceso calibrados al régimen nominal o inyecta el escenario de falla seleccionado."""
    t_actual = int(time.time())
    modo_efectivo = modo
    if modo_efectivo == "normal" and (simular_anomalia or (ciclo > 0 and ciclo % 12 == 0)):
        modo_efectivo = "overload_vfd"

    estado_op = "Produccion"
    tipo_asf = "Plastomerico" if modo_efectivo == "exchanger_fouling" else "Convencional"
    es_plasto = 1 if tipo_asf == "Plastomerico" else 0

    # Valores nominales calibrados con el modelo entrenado (Produccion|Convencional / Plastomerico)
    temp_betun = (153.2 if es_plasto else 134.7) + random.uniform(-0.4, 0.4)
    volt_betun = 23.76 + random.uniform(-0.02, 0.02)
    amp_eco_betum = 52.33 + random.uniform(-0.3, 0.3)
    est_radar = 0.0
    amp_cau_sol = 13.31 + random.uniform(-0.1, 0.1)
    amp_motor = (113.8 if es_plasto else 105.7) + random.uniform(-0.8, 0.8)
    tor_motor = (77.2 if es_plasto else 71.7) + random.uniform(-0.6, 0.6)
    vib_motor = (2.56 if es_plasto else 2.47) + random.uniform(-0.04, 0.04)
    pre_filtro = (0.48 if es_plasto else 0.42) + random.uniform(-0.015, 0.015)
    pre_inter = (1.16 if es_plasto else 0.0) + (random.uniform(-0.02, 0.02) if es_plasto else 0.0)
    cau_bomba = (170.3 if es_plasto else 180.6) + random.uniform(-1.5, 1.5)
    rpm_molino = 2898.0 + random.uniform(-5.0, 5.0)

    # Inyección controlada por modo de falla (7 modos del sistema)
    if modo_efectivo == "overload_vfd":
        temp_betun = 118.5 + random.uniform(-1.0, 1.0)
        amp_motor = 138.0 + random.uniform(0.0, 4.0)
        tor_motor = 94.5 + random.uniform(0.0, 2.5)
    elif modo_efectivo == "clogged_filter":
        pre_filtro = 1.48 + random.uniform(0.0, 0.12)
        cau_bomba = 136.0 + random.uniform(-3.0, 2.0)
    elif modo_efectivo == "radar_dirty":
        amp_eco_betum = 26.0 + random.uniform(-2.0, 1.5)
        est_radar = 2.0
    elif modo_efectivo == "short_circuit":
        amp_cau_sol = 20.8 + random.uniform(0.0, 0.5)
    elif modo_efectivo == "pt100_drift":
        volt_betun = 21.1 + random.uniform(-0.2, 0.1)
    elif modo_efectivo == "exchanger_fouling":
        pre_inter = 4.85 + random.uniform(0.0, 0.35)
    elif modo_efectivo == "bearing_wear":
        vib_motor = 6.95 + random.uniform(0.0, 0.35)

    lectura_validada = Lectura31Molino(
        ESTADO_operacion=estado_op,
        TIPO_asfalto=tipo_asf,
        TEM_son_betum_in=round(temp_betun, 2),
        RES_son_betum_in=round(151.86 + (temp_betun - 134.7) * 0.38, 2),
        VOLT_son_betum_in=round(volt_betun, 2),
        AMP_son_betum_in=round(12.62 + (temp_betun - 134.7) * 0.08, 2),
        AMP_cau_betum_in=round(12.3 + random.uniform(-0.1, 0.1), 2),
        FRE_cau_betum_in=round(249.5 + random.uniform(-1.5, 1.5), 2),
        AMP_eco_betum_dep=round(amp_eco_betum, 2),
        EST_niv_betum_dep=float(est_radar),
        TEM_son_solucion_in=round(36.4 + random.uniform(-0.3, 0.3), 2),
        RES_son_solucion_in=114.01,
        AMP_son_solucion_in=9.82,
        AMP_cau_solucion_in=round(amp_cau_sol, 2),
        FRE_cau_solucion_in=round(400.0 + random.uniform(-2.0, 2.0), 2),
        AMP_eco_solucion_dep=70.0,
        TEM_son_emulsion_out=round(72.5 + random.uniform(-0.4, 0.4), 2),
        RES_son_emulsion_out=127.91,
        AMP_cau_emulsion_out=round(14.44 + random.uniform(-0.1, 0.1), 2),
        FRE_cau_emulsion_out=round(322.7 + random.uniform(-2.0, 2.0), 2),
        AMP_eco_emulsion_dep=60.0,
        RPM_motor_molino=round(rpm_molino, 1),
        FRE_vfd_motor_molino=50.0,
        AMP_vfd_motor_molino=round(amp_motor, 2),
        TOR_vfd_motor_molino=round(tor_motor, 1),
        VIB_vel_motor_molino=round(vib_motor, 2),
        AMP_vib_motor_molino=round(5.58 + (vib_motor - 2.47) * 0.64, 2),
        CAU_bomba_lpm=round(cau_bomba, 1),
        PRE_dif_filtro_bar=round(pre_filtro, 2),
        TEM_emulsion_molino_out=round(73.5 + random.uniform(-0.4, 0.4), 2),
        PRE_intercambiador_bar=round(pre_inter, 2),
        es_plastomerico=es_plasto,
        en_limpieza=1 if estado_op == "Limpieza" else 0,
    ).model_dump()

    # Formato híbrido: 31 variables en raíz (para Firehose/Parquet glue_table.json) + lectura_actual
    return {
        "equipo_id": "MOLINO_QLA_01",
        "timestamp": t_actual,
        **lectura_validada,
        "lectura_actual": lectura_validada,
    }


def main():
    parser = argparse.ArgumentParser(description="Simulador de Telemetría MC-01 hacia AWS IoT Core")
    parser.add_argument("--intervalo", type=float, default=2.0, help="Segundos entre cada envío (default: 2.0s)")
    parser.add_argument("--cantidad", type=int, default=30, help="Total de lecturas a enviar (0 para infinito)")
    parser.add_argument("--anomalia", action="store_true", help="Forzar anomalía de sobrecarga y asfalto frío")
    parser.add_argument("--modo", choices=MODOS_SIMULACION, default="normal", help="Modo operativo o falla a inyectar")
    args = parser.parse_args()

    print("=" * 65)
    print(">> TRANSMISOR DE TELEMETRIA EN VIVO (EDGE -> AWS IOT CORE)")
    print("=" * 65)
    print(f" Broker Endpoint : {IOT_ENDPOINT}")
    print(f" Topic MQTT      : {TOPIC_TELEMETRIA}")
    print(f" Modo Simulacion : {args.modo}")
    print(f" Intervalo envio : {args.intervalo} seg | Total envios: {'Infinito' if args.cantidad == 0 else args.cantidad}")
    print("=" * 65)

    iot_client = boto3.client("iot-data", region_name=REGION, endpoint_url=IOT_ENDPOINT)
    cola = ColaStoreAndForward()

    enviados = 0
    try:
        while True:
            enviados += 1
            payload = generar_lectura(enviados, simular_anomalia=args.anomalia, modo=args.modo)

            # 1. Publicar a AWS IoT Core con resiliencia Store-and-Forward (SQLite WAL)
            try:
                cola.drenar(iot_client, TOPIC_TELEMETRIA)
                iot_client.publish(
                    topic=TOPIC_TELEMETRIA,
                    qos=1,
                    payload=json.dumps(payload),
                )
            except Exception:
                cola.encolar(payload)

            # 2. Enviar al backend local (Hot Path WebSocket para visualización en vivo)
            try:
                import urllib.request
                req_local = urllib.request.Request(
                    "http://127.0.0.1:8000/api/telemetria",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req_local, timeout=1)
            except Exception:
                pass

            l = payload["lectura_actual"]
            hora = datetime.datetime.now().strftime("%H:%M:%S")
            alerta = " [!] ALERTA ANOMALIA" if (l["TEM_son_betum_in"] < 130 or l["AMP_vfd_motor_molino"] > 120 or l["PRE_dif_filtro_bar"] > 1.0 or l["VIB_vel_motor_molino"] > 4.0 or l["EST_niv_betum_dep"] >= 1.0) else ""

            print(
                f"[{hora}] #{enviados:03d} ({args.modo}) -> Betun: {l['TEM_son_betum_in']:5.1f}C "
                f"| Motor: {l['AMP_vfd_motor_molino']:5.1f}A | Vib: {l['VIB_vel_motor_molino']:4.2f} mm/s "
                f"| dP Filtro: {l['PRE_dif_filtro_bar']:4.2f} bar{alerta}"
            )

            if args.cantidad > 0 and enviados >= args.cantidad:
                break

            time.sleep(args.intervalo)

    except KeyboardInterrupt:
        print("\n[!] Simulacion detenida por el usuario.")

    print("\n[OK] Proceso de simulacion finalizado.")


if __name__ == "__main__":
    main()
