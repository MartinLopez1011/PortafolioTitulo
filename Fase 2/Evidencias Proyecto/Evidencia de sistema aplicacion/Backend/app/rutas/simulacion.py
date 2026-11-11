"""Control del simulador de la planta (HU-17 a HU-19). Disponible para operador y administrador."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import config
from ..seguridad import OPERADOR, requiere_nivel
from ..simulador import SimuladorNoDisponible, simulador

router = APIRouter(prefix="/simulacion", tags=["Simulación"])
lector = requiere_nivel(OPERADOR)


class Control(BaseModel):
    accion: Literal["iniciar", "pausar", "velocidad", "saltar_paradas", "ir_a", "modo", "escenario"]
    valor: str | None = None


def _sin_demo():
    if config.MODO_DEMO:
        raise HTTPException(409, "El simulador necesita la base de datos (no disponible en modo demostración)")


@router.get("", summary="Estado del simulador")
def estado(u: dict = Depends(lector)):
    if config.MODO_DEMO:
        from .. import demo_store
        return demo_store.obtener_simulacion_estado_demo()
    return simulador.estado()


@router.get("/opciones", summary="Velocidades, modos, fallas y fechas disponibles")
async def opciones(u: dict = Depends(lector)):
    if config.MODO_DEMO:
        from .. import demo_store
        return demo_store.obtener_simulacion_opciones_demo()
    try:
        # la primera vez carga el dataset del año (unos segundos)
        return await run_in_threadpool(simulador.opciones)
    except SimuladorNoDisponible as e:
        raise HTTPException(503, str(e))


@router.post("", summary="Controlar el simulador")
async def controlar(c: Control, u: dict = Depends(lector)):
    if config.MODO_DEMO:
        from .. import demo_store
        return demo_store.controlar_simulacion_demo(c.accion, c.valor)
    try:
        r = await run_in_threadpool(simulador.controlar, c.accion, c.valor)
    except SimuladorNoDisponible as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return r
