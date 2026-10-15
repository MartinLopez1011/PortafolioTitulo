import io
import json
import logging
import os
import time
from decimal import Decimal
import boto3
import pandas as pd

# Configuración de logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Variable global para motor de inferencia (lazy-loading en warm-start)
engine = None


def get_engine():
    global engine
    if engine is None:
        try:
            logger.info("Cargando motor de inferencia...")
            from app.inference_engine import MolinoInferenceEngine
            engine = MolinoInferenceEngine()
            logger.info("Motor de inferencia cargado exitosamente.")
        except Exception as e:
            logger.error(f"Error inicializando modelos de inferencia: {e}", exc_info=True)
            engine = None
    return engine

# Cliente DynamoDB
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "QLA_Molino_Telemetria")
dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

# Cliente AWS IoT Core (Data-ATS)
# AWS IoT Data requiere endpoint_url (ATS endpoint asignado a tu cuenta)
IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT", "https://a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com")
if not IOT_ENDPOINT.startswith("https://"):
    IOT_ENDPOINT = f"https://{IOT_ENDPOINT}"

iot_client = boto3.client(
    "iot-data",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    endpoint_url=IOT_ENDPOINT
)

# Configuración y Cliente S3 (Ventana Activa y Bitácora para Modelo 3)
BUCKET_NAME = os.environ.get("S3_BUCKET", "backup-planta-asfalto-molino-ml")
S3_VENTANA_PATH = f"s3://{BUCKET_NAME}/ventana_activa/ultimas_168_horas.parquet"
S3_BITACORA_KEY = os.environ.get("S3_BITACORA_KEY", "bitacora/estado_equipos.json")
s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def obtener_bitacora(equipo_id: str) -> dict:
    """Lee el estado de mantenciones desde S3"""
    try:
        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=S3_BITACORA_KEY)
        bitacora = json.loads(obj["Body"].read().decode("utf-8"))
        return bitacora.get(equipo_id, {})
    except Exception as e:
        logger.warning(f"No se pudo leer bitácora desde S3 ({e})")
        return {}


def actualizar_ventana_168h(nueva_lectura: dict) -> pd.DataFrame:
    """
    Lee las últimas horas, añade la nueva lectura y guarda el parquet con un máximo de 168 filas.
    Tiempo de ejecución típico: ~90-140ms
    """
    df_nuevo = pd.DataFrame([nueva_lectura])
    df_completo = df_nuevo
    key = "ventana_activa/ultimas_168_horas.parquet"

    # 1. Intentar leer la ventana actual desde S3 usando boto3
    try:
        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        df_historico = pd.read_parquet(io.BytesIO(obj["Body"].read()))
        df_completo = pd.concat([df_historico, df_nuevo], ignore_index=True)
    except Exception as e:
        logger.info(f"Iniciando nueva ventana activa en S3 ({e})")
        df_completo = df_nuevo

    # 2. Conservar solo las últimas 168 filas (7 días a razón de 1 fila horaria)
    df_ventana = df_completo.tail(168)

    # 3. Sobrescribir el parquet en S3 usando boto3
    try:
        buffer = io.BytesIO()
        df_ventana.to_parquet(buffer, index=False)
        buffer.seek(0)
        s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=buffer.getvalue())
    except Exception as e_s3_put:
        logger.warning(f"Advertencia al guardar ventana activa en S3: {e_s3_put}")

    return df_ventana


def _convert_floats_to_decimal(obj):
    """DynamoDB requiere tipo Decimal en lugar de float."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def lambda_handler(event, context):
    """
    Handler principal de inferencia en tiempo real para el Molino Coloidal QLA.
    Recibe la telemetría del edge gateway, procesa diagnóstico/vigilancia y persiste en DynamoDB.
    """
    logger.info(f"Evento recibido: {json.dumps(event)}")

    eng = get_engine()
    if eng is None:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "El motor de inferencia no se pudo inicializar."})
        }

    try:
        # Soportar si el evento viene como string JSON
        if isinstance(event, str):
            event = json.loads(event)

        # Si viene a través de Function URL o API Gateway, el payload está en event["body"]
        if isinstance(event, dict) and "body" in event and event["body"]:
            if isinstance(event["body"], str):
                event = json.loads(event["body"])
            elif isinstance(event["body"], dict):
                event = event["body"]

        # Extraer lectura actual
        lectura = event.get("lectura_actual", event)
        equipo_id = event.get("equipo_id", "MOLINO_QLA_01")
        timestamp = int(event.get("timestamp", time.time()))

        # 1. Ejecutar Inferencia de Diagnóstico y Vigilancia (Tiempo Real)
        resultado_inferencia = eng.ejecutar_tiempo_real(lectura)

        # 2. Mantener ventana activa de 168 horas y consultar bitácora en S3
        try:
            df_ventana = actualizar_ventana_168h(lectura)
            bitacora_equipo = obtener_bitacora(equipo_id)
            resultado_inferencia["estado_equipos_s3"] = bitacora_equipo
            logger.info(f"Ventana activa en S3 actualizada ({len(df_ventana)} registros).")
        except Exception as e_s3:
            logger.warning(f"Advertencia al gestionar ventana activa/bitácora en S3: {e_s3}")

        # 3. Si vienen features para modelos predictivos (80 features), ejecutarlos también
        if "features_predictivo" in event or all(col in lectura for col in eng.features_80):
            try:
                features_pred = event.get("features_predictivo", lectura)
                resultado_predictivo = eng.ejecutar_predictivo(features_pred)
                resultado_inferencia["predictivo"] = resultado_predictivo
            except Exception as e_pred:
                logger.warning(f"No se pudo ejecutar módulo predictivo tabular: {e_pred}")

        # 4. Guardar telemetría e inferencia en DynamoDB
        registro_dynamo = {
            "equipo_id": equipo_id,
            "timestamp": timestamp,
            "lectura": lectura,
            "diagnostico": resultado_inferencia.get("diagnostico", {}),
            "vigilancia": resultado_inferencia.get("vigilancia_autoencoder", {}),
            "estado_operacion": resultado_inferencia.get("estado_operacion", "Desconocido")
        }

        try:
            table.put_item(Item=_convert_floats_to_decimal(registro_dynamo))
            logger.info("Registro guardado exitosamente en DynamoDB.")
        except Exception as e_db:
            logger.warning(f"Advertencia al escribir en DynamoDB: {e_db}")

        # 5. Publicar predicciones en AWS IoT Core (MQTT)
        try:
            diag = resultado_inferencia.get("diagnostico", {})
            ae = resultado_inferencia.get("vigilancia_autoencoder", {})
            alerta = diag.get("anomalia_confirmada", False) or ae.get("alerta_anomalia_nueva", False)

            # Extraer probabilidades de horizontes predictivos si existen
            prob_24h = 0.0
            prob_5d = 0.0
            prob_15d = 0.0

            predictivo = resultado_inferencia.get("predictivo", {})
            for alerta_prev in predictivo.get("alertas_preventivas", []):
                horiz = alerta_prev.get("horizonte", "")
                p = float(alerta_prev.get("probabilidad", 0.0))
                if "24" in horiz:
                    prob_24h = max(prob_24h, p)
                elif "5" in horiz:
                    prob_5d = max(prob_5d, p)
                elif "15" in horiz:
                    prob_15d = max(prob_15d, p)

            payload_salida = {
                "equipo_id": equipo_id,
                "timestamp": timestamp,
                "riesgo_24h": round(prob_24h, 4),
                "riesgo_5d": round(prob_5d, 4),
                "riesgo_15d": round(prob_15d, 4),
                "alerta_activa": bool(alerta),
                "falla": diag.get("falla", "Normal"),
                "estado_operacion": resultado_inferencia.get("estado_operacion", "Desconocido")
            }

            iot_client.publish(
                topic="planta/asfalto/molino/predicciones",
                qos=1,
                payload=json.dumps(payload_salida)
            )
            logger.info(f"Predicciones publicadas exitosamente en AWS IoT Core: {payload_salida}")
        except Exception as e_iot:
            logger.warning(f"Advertencia al publicar en AWS IoT Core: {e_iot}")

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "equipo_id": equipo_id,
                "timestamp": timestamp,
                "resultado": resultado_inferencia
            })
        }

    except Exception as e:
        logger.error(f"Error procesando inferencia: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)})
        }
