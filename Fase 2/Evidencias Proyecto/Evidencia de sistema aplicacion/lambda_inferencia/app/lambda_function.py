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

# Variable global para motor de inferencia (pre-cargado en fase INIT / Warm Start de AWS Lambda)
engine = None


def get_engine():
    global engine
    if engine is None:
        try:
            logger.info("Cargando motor de inferencia en memoria global (Warm Start)...")
            from app.inference_engine import MolinoInferenceEngine
            engine = MolinoInferenceEngine()
            logger.info("Motor de inferencia cargado exitosamente.")
        except Exception as e:
            logger.error(f"Error inicializando modelos de inferencia: {e}", exc_info=True)
            engine = None
    return engine


# Pre-cargar modelos en el scope global durante el arranque del contenedor
get_engine()

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
    Lee las últimas 168 horas desde S3, consolida a resolución de 1 minuto para evitar que
    ráfagas sub-minuto sobrescriban la ventana de 7 días, y persiste el Parquet actualizado.
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

    # 2. Normalizar timestamp epoch y consolidar duplicados dentro del mismo minuto
    try:
        ts_num = pd.to_numeric(df_completo["timestamp"], errors="coerce")
        if ts_num.isna().any():
            ts_parsed = pd.to_datetime(df_completo["timestamp"], utc=True, errors="coerce")
            ts_num = ts_num.fillna((ts_parsed.astype("int64") // 10**9).astype(float))
        df_completo["timestamp"] = ts_num.fillna(int(time.time())).astype(int)
        df_completo["_min_bucket"] = df_completo["timestamp"] // 60
        df_completo = (
            df_completo.sort_values("timestamp")
            .drop_duplicates(subset=["_min_bucket"], keep="last")
            .drop(columns=["_min_bucket"])
        )
        max_ts = int(df_completo["timestamp"].max())
        corte_168h = max_ts - (168 * 3600)
        df_ventana = df_completo[df_completo["timestamp"] >= corte_168h].tail(10080).reset_index(drop=True)
    except Exception as e_norm:
        logger.warning(f"Fallback en poda de ventana 168h: {e_norm}")
        df_ventana = df_completo.tail(10080).reset_index(drop=True)

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

        # Extraer lectura actual y arreglarla al contrato canónico de 31 variables de entrada
        lectura_cruda = event.get("lectura_actual", event)
        if not isinstance(lectura_cruda, dict):
            lectura_cruda = dict(event)
        else:
            lectura_cruda = dict(lectura_cruda)
            for k_meta in ("timestamp", "equipo_id", "ESTADO_operacion", "TIPO_asfalto", "es_plastomerico", "en_limpieza"):
                if k_meta in event and k_meta not in lectura_cruda:
                    lectura_cruda[k_meta] = event[k_meta]

        equipo_id = str(event.get("equipo_id") or lectura_cruda.get("equipo_id") or "MOLINO_QLA_01")
        timestamp = eng._normalizar_timestamp_epoch(event.get("timestamp", lectura_cruda.get("timestamp")))
        lectura_cruda["timestamp"] = timestamp

        # 0. Normalizar siempre a las 31 variables de entrada (29 sensores + es_plastomerico + en_limpieza)
        lectura_31 = eng.Normalizar_Entrada_31(lectura_cruda)

        # 1. Ejecutar Inferencia de Diagnóstico (Modelo 1) y Vigilancia (Modelo 2) con las 31 variables
        resultado_inferencia = eng.ejecutar_tiempo_real(lectura_31)

        # 2. Mantener ventana activa en S3 con las 31 variables y consultar bitácora
        df_ventana_31 = pd.DataFrame([lectura_31])
        bitacora_equipo = {}
        try:
            df_ventana_31 = actualizar_ventana_168h(lectura_31)
            bitacora_equipo = obtener_bitacora(equipo_id)
            resultado_inferencia["estado_equipos_s3"] = bitacora_equipo
            logger.info(f"Ventana activa de 31 variables en S3 actualizada ({len(df_ventana_31)} registros).")
        except Exception as e_s3:
            logger.warning(f"Advertencia al gestionar ventana activa/bitácora en S3: {e_s3}")

        # 3. Ejecutar Modelo 3 (Predictivo): refactoriza las 31 variables de entrada -> 11 base -> 80 tabulares
        try:
            if "features_predictivo" in event:
                resultado_predictivo = eng.ejecutar_predictivo(event["features_predictivo"], bitacora_equipo)
            else:
                resultado_predictivo = eng.ejecutar_predictivo_desde_31(df_ventana_31, bitacora_equipo)
            resultado_inferencia["predictivo"] = resultado_predictivo
        except Exception as e_pred:
            logger.warning(f"No se pudo ejecutar módulo predictivo tabular (31->11->80): {e_pred}", exc_info=True)

        # 4. Guardar telemetría (31 variables) e inferencia en DynamoDB
        registro_dynamo = {
            "equipo_id": equipo_id,
            "timestamp": timestamp,
            "lectura": lectura_31,
            "diagnostico": resultado_inferencia.get("diagnostico", {}),
            "vigilancia": resultado_inferencia.get("vigilancia_autoencoder", {}),
            "predictivo": resultado_inferencia.get("predictivo", {}),
            "estado_operacion": resultado_inferencia.get("estado_operacion", lectura_31.get("ESTADO_operacion", "Desconocido"))
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
            predictivo = resultado_inferencia.get("predictivo", {})
            alertas_prev = predictivo.get("alertas_preventivas", [])

            # Extraer probabilidades máximas y modo de falla dominante por horizonte
            prob_24h, falla_24h = 0.0, "Normal"
            prob_5d, falla_5d = 0.0, "Normal"
            prob_15d, falla_15d = 0.0, "Normal"

            for nombre_falla, info_falla in predictivo.get("pronosticos", {}).items():
                for horiz, det in info_falla.get("horizontes", {}).items():
                    p = float(det.get("probabilidad", 0.0))
                    if "24" in horiz and p >= prob_24h:
                        prob_24h = p
                        if p > 0:
                            falla_24h = nombre_falla
                    elif "5" in horiz and p >= prob_5d:
                        prob_5d = p
                        if p > 0:
                            falla_5d = nombre_falla
                    elif "15" in horiz and p >= prob_15d:
                        prob_15d = p
                        if p > 0:
                            falla_15d = nombre_falla

            for alerta_p in alertas_prev:
                horiz = alerta_p.get("horizonte", "")
                p = float(alerta_p.get("probabilidad", 0.0))
                f_cod = alerta_p.get("falla", "Normal")
                if "24" in horiz and p >= prob_24h:
                    prob_24h, falla_24h = p, f_cod
                elif "5" in horiz and p >= prob_5d:
                    prob_5d, falla_5d = p, f_cod
                elif "15" in horiz and p >= prob_15d:
                    prob_15d, falla_15d = p, f_cod

            alerta = bool(
                diag.get("anomalia_confirmada", False)
                or ae.get("alerta_anomalia_nueva", False)
                or len(alertas_prev) > 0
            )

            falla_principal = diag.get("falla", "Normal")
            accion_principal = diag.get("accion")
            if falla_principal == "Normal":
                if alertas_prev:
                    alerta_top = max(alertas_prev, key=lambda a: float(a.get("probabilidad", 0.0)))
                    falla_principal = alerta_top.get("falla", "Normal")
                    accion_principal = alerta_top.get("accion_recomendada")
                elif ae.get("alerta_anomalia_nueva", False):
                    falla_principal = "Desviacion_Multivariante_Autoencoder"
                    accion_principal = "Inspeccionar sensores con mayor error cuadrático en vigilancia Autoencoder."

            payload_salida = {
                "equipo_id": equipo_id,
                "timestamp": timestamp,
                "riesgo_24h": round(prob_24h, 4),
                "riesgo_5d": round(prob_5d, 4),
                "riesgo_15d": round(prob_15d, 4),
                "falla_24h": falla_24h,
                "falla_5d": falla_5d,
                "falla_15d": falla_15d,
                "alerta_activa": alerta,
                "falla": falla_principal,
                "accion_recomendada": accion_principal or "Operación dentro de parámetros nominales.",
                "mse_autoencoder": ae.get("mse", 0.0),
                "indice_salud": round(max(0.0, 100.0 - min(100.0, float(ae.get("indice_salud_ratio", 0.0)) * 25.0)), 1),
                "estado_operacion": resultado_inferencia.get("estado_operacion", lectura_31.get("ESTADO_operacion", "Produccion")),
                "tipo_asfalto": resultado_inferencia.get("tipo_asfalto", lectura_31.get("TIPO_asfalto", "Convencional")),
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
