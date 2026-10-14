import json
import logging
import os
import time
from decimal import Decimal
import boto3

from app.inference_engine import MolinoInferenceEngine

# Configuración de logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Inicialización en frío del motor de inferencia (reutilizado en warm-start)
try:
    engine = MolinoInferenceEngine()
    logger.info("Motor de inferencia cargado exitosamente.")
except Exception as e:
    logger.error(f"Error inicializando modelos de inferencia: {e}", exc_info=True)
    engine = None

# Cliente DynamoDB
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "QLA_Molino_Telemetria")
dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
table = dynamodb.Table(DYNAMODB_TABLE_NAME)


def _convert_floats_to_decimal(obj):
    """DynamoDB requiere tipo Decimal en lugar de float."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def lambda_handler(event, context):
    """
    Handler principal de inferencia en tiempo real para el Molino Coloidal QLA.
    Recibe la telemetría del edge gateway, procesa diagnóstico/vigilancia y persiste en DynamoDB.
    """
    logger.info(f"Evento recibido: {json.dumps(event)}")

    if engine is None:
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
        resultado_inferencia = engine.ejecutar_tiempo_real(lectura)

        # 2. Si vienen features para modelos predictivos (80 features), ejecutarlos también
        if "features_predictivo" in event or any(col in lectura for col in engine.features_80):
            try:
                features_pred = event.get("features_predictivo", lectura)
                resultado_predictivo = engine.ejecutar_predictivo(features_pred)
                resultado_inferencia["predictivo"] = resultado_predictivo
            except Exception as e_pred:
                logger.warning(f"No se pudo ejecutar módulo predictivo tabular: {e_pred}")

        # 3. Guardar telemetría e inferencia en DynamoDB
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
