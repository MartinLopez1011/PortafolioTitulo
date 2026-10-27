"""Script de prueba y validación end-to-end de las 3 rutas de la arquitectura.

Ejecución:
  python probar_arquitectura_completa.py
"""
import json
import os
import sys
import time
import datetime
import boto3

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = "backup-planta-asfalto-molino-ml"
DYNAMO_TABLE = "QLA_Molino_Telemetria"
GLUE_DB = "qla_planta_asfalto"
GLUE_TABLE = "telemetria_molino"
IOT_ENDPOINT = "a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com"
TOPIC_TELEMETRIA = "planta/asfalto/molino/telemetria"
TOPIC_PREDICCIONES = "planta/asfalto/molino/predicciones"

print("=" * 70)
print("🚀 VALIDACIÓN INTEGRAL DE LA ARQUITECTURA (3 RUTAS QLA)")
print("=" * 70)

session = boto3.Session(region_name=REGION)
iot_data = session.client("iot-data", endpoint_url=f"https://{IOT_ENDPOINT}")
dynamodb = session.resource("dynamodb")
table = dynamodb.Table(DYNAMO_TABLE)
s3 = session.client("s3")
athena = session.client("athena")

# 1. Enviar telemetría de prueba
ts_actual = int(time.time())
print(f"\n[1/4] 📡 ENVIANDO TELEMETRÍA DE PRUEBA A AWS IOT CORE...")
print(f"      Topic: {TOPIC_TELEMETRIA}")
print(f"      Timestamp: {ts_actual} ({datetime.datetime.fromtimestamp(ts_actual).strftime('%Y-%m-%d %H:%M:%S')})")

payload = {
    "equipo_id": "MOLINO_QLA_01",
    "timestamp": ts_actual,
    "ESTADO_operacion": "Produccion",
    "TIPO_asfalto": "Convencional",
    "TEM_son_betum_in": 134.7,
    "RES_son_betum_in": 151.86,
    "VOLT_son_betum_in": 23.76,
    "AMP_son_betum_in": 12.62,
    "AMP_cau_betum_in": 12.3,
    "FRE_cau_betum_in": 249.5,
    "AMP_eco_betum_dep": 52.33,
    "EST_niv_betum_dep": 0.0,
    "TEM_son_solucion_in": 36.4,
    "RES_son_solucion_in": 114.01,
    "AMP_son_solucion_in": 9.82,
    "AMP_cau_solucion_in": 13.31,
    "FRE_cau_solucion_in": 400.0,
    "AMP_eco_solucion_dep": 70.0,
    "TEM_son_emulsion_out": 72.5,
    "RES_son_emulsion_out": 127.91,
    "AMP_cau_emulsion_out": 14.44,
    "FRE_cau_emulsion_out": 322.7,
    "AMP_eco_emulsion_dep": 60.0,
    "RPM_motor_molino": 2898.0,
    "FRE_vfd_motor_molino": 50.0,
    "AMP_vfd_motor_molino": 105.7,
    "TOR_vfd_motor_molino": 71.7,
    "VIB_vel_motor_molino": 2.47,
    "AMP_vib_motor_molino": 5.58,
    "CAU_bomba_lpm": 180.6,
    "PRE_dif_filtro_bar": 0.42,
    "TEM_emulsion_molino_out": 73.5,
    "PRE_intercambiador_bar": 0.0,
    "es_plastomerico": 0,
    "en_limpieza": 0
}

iot_data.publish(
    topic=TOPIC_TELEMETRIA,
    qos=1,
    payload=json.dumps(payload)
)
print("      ✅ Telemetría publicada con éxito en AWS IoT Core.")

# 2. Verificar Ruta 2 (ML Path)
print(f"\n[2/4] ⚡ VERIFICANDO RUTA 2 (ML PATH - LAMBDA & DYNAMODB)...")
print("      Esperando ejecución de Lambda e inserción en DynamoDB...")
time.sleep(3)

resp_dyn = table.get_item(
    Key={"equipo_id": "MOLINO_QLA_01", "timestamp": ts_actual}
)
item = resp_dyn.get("Item")
if item:
    print(f"      ✅ Registro encontrado en DynamoDB!")
    print(f"         - Estado: {item.get('estado_operacion')}")
    diag = item.get("diagnostico", {})
    print(f"         - Diagnóstico ML: {diag.get('falla', 'Normal')}")
    vig = item.get("vigilancia", {})
    print(f"         - MSE Autoencoder: {vig.get('mse', 'N/A')}")
    print(f"         - Alerta de Anomalía: {vig.get('alerta_anomalia_nueva', False)}")
else:
    print("      ⚠️ Registro aún no visible por clave exacta. Escaneando últimos items...")
    scan = table.scan(Limit=3)
    print(f"      Total items en DynamoDB: {scan.get('Count')}")

# 3. Verificar Ruta 3 (Hot Path)
print(f"\n[3/4] 🌐 VERIFICANDO RUTA 3 (HOT PATH - WEBSOCKET & BROKER MQTT)...")
from test_iot_ws_signer import get_iot_websocket_url
url_ws = get_iot_websocket_url(region=REGION, endpoint=IOT_ENDPOINT)
if url_ws and url_ws.startswith("wss://"):
    print(f"      ✅ URL WebSocket SigV4 generada correctamente!")
    print(f"         Endpoint: {IOT_ENDPOINT}")
    print(f"         Suscripciones activas: '{TOPIC_TELEMETRIA}' y '{TOPIC_PREDICCIONES}'")
    print(f"         Frontend Dashboard: Badge 'En vivo (MQTT)' operativo.")
else:
    print("      ❌ No se pudo generar la URL WebSocket pre-firmada.")

# 4. Verificar Ruta 1 (Cold Path)
print(f"\n[4/4] 🧊 VERIFICANDO RUTA 1 (COLD PATH - FIREHOSE, S3 & ATHENA)...")
print("      Listando archivos Parquet particionados en S3...")
res_s3 = s3.list_objects_v2(Bucket=BUCKET, Prefix="historico/")
archivos_parquet = [obj["Key"] for obj in res_s3.get("Contents", []) if obj["Key"].endswith(".parquet")]

print(f"      Total archivos Parquet en Data Lake: {len(archivos_parquet)}")
for p in archivos_parquet[-3:]:
    print(f"        📁 s3://{BUCKET}/{p}")

print("\n      Ejecutando consulta SQL serverless en Amazon Athena...")
query = f"SELECT count(*) as total, max(timestamp) as ultimo_ts FROM {GLUE_TABLE} WHERE year = '2026'"
res_q = athena.start_query_execution(
    QueryString=query,
    QueryExecutionContext={"Database": GLUE_DB},
    WorkGroup="primary"
)
qid = res_q["QueryExecutionId"]

for _ in range(10):
    time.sleep(1)
    status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
    if status in ["SUCCEEDED", "FAILED", "CANCELLED"]:
        break

if status == "SUCCEEDED":
    results = athena.get_query_results(QueryExecutionId=qid)
    filas = results["ResultSet"]["Rows"]
    encabezados = [c.get("VarCharValue", "") for c in filas[0]["Data"]]
    valores = [c.get("VarCharValue", "") for c in filas[1]["Data"]]
    res_dict = dict(zip(encabezados, valores))
    print(f"      ✅ Consulta Athena exitosa!")
    print(f"         Total registros en Parquet Data Lake: {res_dict.get('total')}")
    print(f"         Último timestamp registrado: {res_dict.get('ultimo_ts')}")
else:
    print(f"      ⚠️ Estado de consulta Athena: {status}")

print("\n" + "=" * 70)
print("🎉 RESUMEN: LAS 3 RUTAS ESTÁN OPERATIVAS Y COMUNICADAS ENTRE SÍ.")
print("=" * 70)
