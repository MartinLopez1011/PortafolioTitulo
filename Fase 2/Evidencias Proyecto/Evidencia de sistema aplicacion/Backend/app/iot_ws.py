"""Generador de URL pre-firmada SigV4 para conexión WebSocket con AWS IoT Core.

Permite al frontend dashboard suscribirse directamente vía MQTT sobre WebSockets
a los topics:
  - planta/asfalto/molino/telemetria (telemetría cruda en tiempo real)
  - planta/asfalto/molino/predicciones (inferencias del modelo ML en tiempo real)
"""
import datetime
import hashlib
import hmac
import logging
import os
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT", "a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com").replace("https://", "").rstrip("/")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _obtener_credenciales():
    """Obtiene credenciales AWS desde boto3 si está disponible, o variables de entorno."""
    try:
        import boto3
        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            frozen = creds.get_frozen_credentials()
            return frozen.access_key, frozen.secret_key, frozen.token
    except Exception as e:
        logger.debug(f"boto3 no disponible o sin credenciales: {e}")

    # Fallback a variables de entorno estándar
    ak = os.environ.get("AWS_ACCESS_KEY_ID")
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY")
    token = os.environ.get("AWS_SESSION_TOKEN")
    if ak and sk:
        return ak, sk, token
    return None, None, None


def generar_iot_websocket_url(region: str = AWS_REGION, endpoint: str = IOT_ENDPOINT) -> Optional[str]:
    """Genera una URL firmada SigV4 para conectar al protocolo MQTT de AWS IoT Core vía WebSockets."""
    ak, sk, token = _obtener_credenciales()
    if not ak or not sk:
        return None

    try:
        t = datetime.datetime.now(datetime.timezone.utc)
        date = t.strftime("%Y%m%d")
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")

        service = "iotdevicegateway"
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date}/{region}/{service}/aws4_request"

        canonical_uri = "/mqtt"
        query_params = {
            "X-Amz-Algorithm": algorithm,
            "X-Amz-Credential": f"{ak}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-SignedHeaders": "host",
        }
        if token:
            query_params["X-Amz-Security-Token"] = token

        sorted_params = sorted(query_params.items())
        canonical_querystring = "&".join(
            [f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}" for k, v in sorted_params]
        )
        canonical_headers = f"host:{endpoint}\n"
        signed_headers = "host"
        payload_hash = hashlib.sha256(b"").hexdigest()

        canonical_request = f"GET\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

        def sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + sk).encode("utf-8"), date)
        k_region = sign(k_date, region)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")

        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        return f"wss://{endpoint}{canonical_uri}?{canonical_querystring}&X-Amz-Signature={signature}"
    except Exception as e:
        logger.error(f"Error generando URL WebSocket pre-firmada para AWS IoT: {e}", exc_info=True)
        return None
