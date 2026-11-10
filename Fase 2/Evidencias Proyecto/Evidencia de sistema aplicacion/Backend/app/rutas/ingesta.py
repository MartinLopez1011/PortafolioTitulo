"""Entrada de datos al sistema y canal en tiempo real hacia el navegador.

* POST /api/ingesta/registro: recibe el resultado de la Lambda de inferencia (el mismo registro
  que guarda en DynamoDB) y lo persiste en la base. Exige la clave X-Clave-Ingesta.
* POST /api/telemetria: telemetría cruda del simulador o del Edge Gateway, solo para difundirla
  en vivo a los navegadores (no se guarda). Exige la clave, salvo desde el mismo servidor (127.0.0.1).
* WS /api/ws/telemetria?token=...: canal en vivo hacia el dashboard. Exige una sesión válida.
"""
import datetime as dt

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import config, persistencia
from ..db import cursor
from ..seguridad import clave_ingesta_valida, token_valido

router = APIRouter(tags=["Ingesta y tiempo real"])

_clientes_ws: set[WebSocket] = set()


def _exigir_clave(clave: str | None, request: Request | None = None, permitir_local: bool = False) -> None:
    if clave_ingesta_valida(clave):
        return
    if permitir_local and request is not None and request.client and request.client.host in ("127.0.0.1", "::1"):
        return
    raise HTTPException(401, "Clave de ingesta inválida o ausente (encabezado X-Clave-Ingesta)")


class Lote(BaseModel):
    registros: list[dict]
    fuente: str = "simulado"
    equipo: str = config.EQUIPO_POR_DEFECTO


@router.post("/ingesta/registro", summary="Guardar resultados de la Lambda de inferencia (servicio)")
async def ingesta_registro(cuerpo: dict, request: Request,
                           x_clave_ingesta: str | None = Header(default=None)):
    """Acepta un registro suelto o {"registros": [...], "fuente": "simulado"|"real"}."""
    _exigir_clave(x_clave_ingesta)
    if config.MODO_DEMO:
        raise HTTPException(409, "En modo demostración no se guardan datos")
    if "registros" in cuerpo:
        lote = Lote(**cuerpo)
    else:
        lote = Lote(registros=[cuerpo], fuente=cuerpo.get("fuente", "simulado"))
    if lote.fuente not in ("simulado", "real"):
        raise HTTPException(422, "fuente debe ser 'simulado' o 'real'")
    resultados = await run_in_threadpool(_guardar_lote, lote)
    # Difusión en vivo del último registro (lecturas + diagnóstico) a los navegadores conectados
    ultimo = lote.registros[-1]
    await difundir({"topic": "planta/asfalto/molino/resultados", "fuente": lote.fuente,
                    "timestamp": ultimo.get("timestamp"), "registro": ultimo,
                    "alarmas": resultados[-1].get("alarmas")})
    return {"guardados": len(resultados), "ultimo": resultados[-1]}


def _guardar_lote(lote: "Lote") -> list[dict]:
    resultados = []
    with cursor() as cur:
        for reg in lote.registros:
            equipo = config.ALIAS_EQUIPO.get(str(reg.get("equipo_id")), lote.equipo)
            resultados.append(persistencia.guardar_registro(cur, reg, lote.fuente, equipo))
    return resultados


@router.post("/telemetria", summary="Telemetría en vivo (solo difusión, no se guarda)")
async def telemetria(datos: dict, request: Request, x_clave_ingesta: str | None = Header(default=None)):
    _exigir_clave(x_clave_ingesta, request, permitir_local=True)
    lectura = datos.get("lectura_actual") or datos
    await difundir({"topic": "planta/asfalto/molino/telemetria",
                    "timestamp": datos.get("timestamp", int(dt.datetime.now(dt.timezone.utc).timestamp())),
                    "equipo_id": datos.get("equipo_id", "MOLINO_QLA_01"),
                    "lectura_actual": lectura})
    return {"status": "ok", "clientes_activos": len(_clientes_ws)}


async def difundir(payload: dict) -> None:
    """Envía un mensaje a todos los navegadores conectados."""
    muertos = []
    for ws in list(_clientes_ws):
        try:
            await ws.send_json(payload)
        except Exception:
            muertos.append(ws)
    for ws in muertos:
        _clientes_ws.discard(ws)


@router.websocket("/ws/telemetria")
async def ws_telemetria(websocket: WebSocket):
    if token_valido(websocket.query_params.get("token")) is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    _clientes_ws.add(websocket)
    try:
        await websocket.send_json({"topic": "sistema", "tipo": "bienvenida",
                                   "timestamp": int(dt.datetime.now(dt.timezone.utc).timestamp())})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clientes_ws.discard(websocket)
