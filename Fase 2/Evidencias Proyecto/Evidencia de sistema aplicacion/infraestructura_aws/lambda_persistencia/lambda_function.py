"""Lambda qla-persistencia: lleva cada resultado de la inferencia desde DynamoDB a la base RDS.

Disparador: DynamoDB Stream de la tabla QLA_Molino_Telemetria (vista NEW_IMAGE).
Por cada lote de registros nuevos llama a POST {URL_BACKEND}/api/ingesta/registro con la clave
X-Clave-Ingesta. El backend guarda en RDS (idempotente: reenviar un registro no lo duplica)
y lo difunde en vivo al dashboard.

Si el backend no responde, la función falla a propósito: el Stream reintenta el mismo lote,
así no se pierde ningún resultado mientras el servidor esté detenido (hasta MAX_EDAD del mapeo).

Variables de entorno:
    URL_BACKEND    p. ej. https://xxxx.execute-api.us-east-1.amazonaws.com
    CLAVE_INGESTA  la misma del .env del backend
    FUENTE         simulado (por defecto) o real
"""
import json
import os
import urllib.error
import urllib.request
from decimal import Decimal

from boto3.dynamodb.types import TypeDeserializer

_deser = TypeDeserializer()
URL = os.environ["URL_BACKEND"].rstrip("/") + "/api/ingesta/registro"
CLAVE = os.environ["CLAVE_INGESTA"]
FUENTE = os.environ.get("FUENTE", "simulado")
TAMANO_ENVIO = 50


def _a_json(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, set):
        return list(v)
    raise TypeError(type(v))


def _enviar(registros: list) -> dict:
    cuerpo = json.dumps({"registros": registros, "fuente": FUENTE}, default=_a_json).encode()
    req = urllib.request.Request(URL, data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json", "X-Clave-Ingesta": CLAVE})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode(errors="replace")
        if e.code in (400, 422):
            # Registro mal formado: reintentarlo no lo arregla. Se registra y se descarta.
            print(f"[DESCARTADO] HTTP {e.code}: {detalle}")
            return {"guardados": 0}
        raise RuntimeError(f"Backend respondió HTTP {e.code}: {detalle}") from None


def lambda_handler(event, context):
    registros = []
    for rec in event.get("Records", []):
        if rec.get("eventName") not in ("INSERT", "MODIFY"):
            continue
        imagen = rec.get("dynamodb", {}).get("NewImage")
        if imagen:
            registros.append({k: _deser.deserialize(v) for k, v in imagen.items()})
    registros.sort(key=lambda r: r.get("timestamp", 0))      # las alarmas 3 de 5 necesitan orden

    guardados = 0
    for i in range(0, len(registros), TAMANO_ENVIO):
        guardados += _enviar(registros[i:i + TAMANO_ENVIO]).get("guardados", 0)
    print(f"[OK] recibidos={len(registros)} guardados={guardados}")
    return {"recibidos": len(registros), "guardados": guardados}
