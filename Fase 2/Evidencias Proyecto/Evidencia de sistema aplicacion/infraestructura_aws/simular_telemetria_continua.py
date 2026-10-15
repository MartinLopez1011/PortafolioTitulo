"""Simulador de flujo continuo de telemetría para el Molino Coloidal MC-01 (QLA).

Publica lecturas periódicas a AWS IoT Core en el topic 'planta/asfalto/molino/telemetria'.
Esto alimenta simultáneamente:
  1. Cold Path: Firehose -> S3 Parquet -> Athena
  2. ML Path: IoT Rule -> Lambda Inferencia -> DynamoDB y alertas
  3. Hot Path: AWS IoT Core WebSockets -> Dashboard Frontend en vivo
"""
import argparse
import datetime
import json
import random
import sys
import time
import boto3

REGION = "us-east-1"
IOT_ENDPOINT = "https://a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com"
TOPIC_TELEMETRIA = "planta/asfalto/molino/telemetria"

def generar_lectura(ciclo: int, simular_anomalia: bool = False):
    """Genera valores de proceso nominales con pequeñas fluctuaciones o anomalía."""
    t_actual = int(time.time())
    
    # Valores base
    temp_betun = 145.0 + random.uniform(-1.2, 1.2)
    amp_motor = 42.5 + random.uniform(-1.0, 1.5)
    vib_motor = 1.25 + random.uniform(-0.1, 0.15)
    pre_filtro = 0.35 + random.uniform(-0.02, 0.03)
    rpm_molino = 2980.0 + random.uniform(-10.0, 10.0)
    
    estado_op = "Produccion"
    
    # Si se pide simular anomalía o cada 15 envíos
    if simular_anomalia or (ciclo > 0 and ciclo % 12 == 0):
        # Simula asfalto frío y sobrecarga del motor
        temp_betun = 128.5 + random.uniform(-1.0, 1.0) # Fuera de rango normal (135-160°C)
        amp_motor = 68.4 + random.uniform(-1.0, 2.0)   # Sobrecarga alta
        vib_motor = 3.40 + random.uniform(0.1, 0.3)    # Vibración alta

    payload = {
        "equipo_id": "MOLINO_QLA_01",
        "timestamp": t_actual,
        "lectura_actual": {
            "ESTADO_operacion": estado_op,
            "TIPO_asfalto": "Convencional",
            "TEM_son_betum_in": round(temp_betun, 2),
            "RES_son_betum_in": round(150.0 + (temp_betun - 140.0) * 0.4, 2),
            "VOLT_son_betum_in": 24.0,
            "AMP_son_betum_in": round(4.0 + random.uniform(0, 0.2), 2),
            "AMP_cau_betum_in": round(12.3 + random.uniform(-0.3, 0.3), 2),
            "FRE_cau_betum_in": 49.9,
            "AMP_eco_betum_dep": 8.5,
            "EST_niv_betum_dep": 65.0,
            "TEM_son_solucion_in": round(48.3 + random.uniform(-0.5, 0.5), 2),
            "RES_son_solucion_in": 118.0,
            "AMP_son_solucion_in": 4.0,
            "AMP_cau_solucion_in": round(9.8 + random.uniform(-0.2, 0.2), 2),
            "FRE_cau_solucion_in": 50.0,
            "AMP_eco_solucion_dep": 7.2,
            "TEM_son_emulsion_out": round(82.5 + random.uniform(-0.6, 0.6), 2),
            "RES_son_emulsion_out": 131.0,
            "AMP_cau_emulsion_out": round(14.1 + random.uniform(-0.3, 0.3), 2),
            "FRE_cau_emulsion_out": 50.1,
            "AMP_eco_emulsion_dep": 9.0,
            "RPM_motor_molino": round(rpm_molino, 1),
            "FRE_vfd_motor_molino": 50.0,
            "AMP_vfd_motor_molino": round(amp_motor, 2),
            "TOR_vfd_motor_molino": round(88.0 + (amp_motor - 42.0) * 1.5, 1),
            "VIB_vel_motor_molino": round(vib_motor, 2),
            "AMP_vib_motor_molino": 0.85,
            "CAU_bomba_lpm": round(260.0 + random.uniform(-5, 5), 1),
            "PRE_dif_filtro_bar": round(pre_filtro, 2),
            "TEM_emulsion_molino_out": round(85.0 + random.uniform(-0.8, 0.8), 2),
            "PRE_intercambiador_bar": round(1.8 + random.uniform(-0.05, 0.05), 2)
        }
    }
    return payload


def main():
    parser = argparse.ArgumentParser(description="Simulador de Telemetría MC-01 hacia AWS IoT Core")
    parser.add_argument("--intervalo", type=float, default=2.0, help="Segundos entre cada envío (default: 2.0s)")
    parser.add_argument("--cantidad", type=int, default=30, help="Total de lecturas a enviar (0 para infinito)")
    parser.add_argument("--anomalia", action="store_true", help="Forzar anomalía de sobrecarga y asfalto frío")
    args = parser.parse_args()

    print("=" * 65)
    print(">> TRANSMISOR DE TELEMETRIA EN VIVO (EDGE -> AWS IOT CORE)")
    print("=" * 65)
    print(f" Broker Endpoint : {IOT_ENDPOINT}")
    print(f" Topic MQTT      : {TOPIC_TELEMETRIA}")
    print(f" Intervalo envio : {args.intervalo} seg | Total envios: {'Infinito' if args.cantidad == 0 else args.cantidad}")
    print("=" * 65)

    iot_client = boto3.client("iot-data", region_name=REGION, endpoint_url=IOT_ENDPOINT)

    enviados = 0
    try:
        while True:
            enviados += 1
            payload = generar_lectura(enviados, simular_anomalia=args.anomalia)
            
            # 1. Publicar a AWS IoT Core (Ruta 1 Cold Path y Ruta 2 ML Path)
            try:
                iot_client.publish(
                    topic=TOPIC_TELEMETRIA,
                    qos=1,
                    payload=json.dumps(payload)
                )
            except Exception as e_iot:
                pass

            # 2. Enviar al backend local (Hot Path WebSocket para visualización en vivo)
            try:
                import urllib.request
                req_local = urllib.request.Request(
                    "http://127.0.0.1:8000/api/telemetria",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req_local, timeout=1)
            except Exception:
                pass
            
            l = payload["lectura_actual"]
            hora = datetime.datetime.now().strftime("%H:%M:%S")
            alerta = " [!] ALERTA ANOMALIA" if l["TEM_son_betum_in"] < 135 or l["AMP_vfd_motor_molino"] > 60 else ""
            
            print(f"[{hora}] #{enviados:03d} -> Betun: {l['TEM_son_betum_in']:5.1f}C | Motor: {l['AMP_vfd_motor_molino']:4.1f}A | Vib: {l['VIB_vel_motor_molino']:4.2f} mm/s | RPM: {l['RPM_motor_molino']:6.1f}{alerta}")

            if args.cantidad > 0 and enviados >= args.cantidad:
                break
                
            time.sleep(args.intervalo)

    except KeyboardInterrupt:
        print("\n[!] Simulacion detenida por el usuario.")
    
    print("\n[OK] Proceso de simulacion finalizado.")

if __name__ == "__main__":
    main()
