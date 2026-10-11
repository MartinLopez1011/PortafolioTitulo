"""API del sistema de mantenimiento predictivo – Química Latinoamericana S.A.

Ejecutar (desde la carpeta Backend):
    uvicorn app.main:app --reload
Documentación interactiva: http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from . import config, db
from .rutas import auth, planta, usuarios


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    config.validar()
    db.abrir()
    yield
    db.cerrar()


app = FastAPI(
    title="API Mantenimiento Predictivo – QLA",
    description="Backend del sistema de mantenimiento predictivo del molino coloidal MC-01. "
                "Para probar: POST /api/auth/login, copie el access_token y péguelo en el botón Authorize.",
    version="0.1.0",
    lifespan=ciclo_de_vida,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
async def base_no_disponible(request: Request, exc: Exception):
    # Ocurre si Supabase está pausado o no hay conexión
    return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible. "
                                                  "Revise que el proyecto de Supabase esté activo."})


@app.get("/api/salud", tags=["Sistema"], summary="Estado de la API y de la base de datos")
def salud():
    with db.cursor() as cur:
        cur.execute("SELECT now() AS hora_bd")
        return {"api": "ok", "base_de_datos": "ok", "hora_bd": cur.fetchone()["hora_bd"]}


app.include_router(auth.router, prefix="/api")
app.include_router(usuarios.router, prefix="/api")
app.include_router(planta.router, prefix="/api")
