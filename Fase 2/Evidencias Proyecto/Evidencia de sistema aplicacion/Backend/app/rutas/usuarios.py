"""Gestión de usuarios y registro de accesos. Solo para el rol administrador."""
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db import cursor
from ..seguridad import ADMINISTRADOR, auditar, hash_clave, ip_cliente, requiere_nivel, validar_clave_nueva

router = APIRouter(prefix="/usuarios", tags=["Usuarios (administrador)"])
solo_admin = requiere_nivel(ADMINISTRADOR)

Rol = Literal["administrador", "supervisor", "operador", "visualizador"]


class UsuarioNuevo(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    rol: Rol
    clave_temporal: str = Field(min_length=8, max_length=72)


class UsuarioCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    rol: Rol | None = None
    activo: bool | None = None


class ClaveTemporal(BaseModel):
    clave_temporal: str = Field(min_length=8, max_length=72)


_SELECT = """SELECT u.id, u.nombre, u.email, r.nombre AS rol, r.nivel, u.activo, u.debe_cambiar_clave,
                    u.bloqueado_hasta, u.ultimo_acceso, u.creado_en
             FROM mantpred.usuarios u JOIN mantpred.roles r ON r.id = u.rol_id"""


@router.get("", summary="Listar usuarios")
def listar(admin: dict = Depends(solo_admin)):
    with cursor() as cur:
        cur.execute(_SELECT + " ORDER BY r.nivel DESC, u.nombre")
        return cur.fetchall()


@router.post("", status_code=201, summary="Crear usuario con contraseña temporal")
def crear(datos: UsuarioNuevo, request: Request, admin: dict = Depends(solo_admin)):
    validar_clave_nueva(datos.clave_temporal)
    email = datos.email.strip().lower()
    try:
        with cursor() as cur:
            cur.execute(
                """INSERT INTO mantpred.usuarios (rol_id, nombre, email, password_hash, debe_cambiar_clave)
                   SELECT id, %s, %s, %s, TRUE FROM mantpred.roles WHERE nombre = %s
                   RETURNING id""",
                (datos.nombre.strip(), email, hash_clave(datos.clave_temporal), datos.rol))
            nuevo_id = cur.fetchone()["id"]
            auditar(cur, admin["id"], admin["email"], ip_cliente(request), "usuario_creado",
                    f"{email} ({datos.rol})")
            cur.execute(_SELECT + " WHERE u.id = %s", (nuevo_id,))
            return cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Ya existe un usuario con ese correo")


@router.patch("/{usuario_id}", summary="Cambiar nombre, rol o estado activo")
def modificar(usuario_id: int, datos: UsuarioCambios, request: Request, admin: dict = Depends(solo_admin)):
    if usuario_id == admin["id"] and (datos.activo is False or (datos.rol and datos.rol != "administrador")):
        raise HTTPException(400, "No puede desactivarse ni quitarse el rol de administrador a sí mismo")
    cambios, valores = [], []
    if datos.nombre is not None:
        cambios.append("nombre = %s"); valores.append(datos.nombre.strip())
    if datos.activo is not None:
        cambios.append("activo = %s"); valores.append(datos.activo)
    if datos.rol is not None:
        cambios.append("rol_id = (SELECT id FROM mantpred.roles WHERE nombre = %s)"); valores.append(datos.rol)
    if not cambios:
        raise HTTPException(422, "No se indicó ningún cambio")
    with cursor() as cur:
        cur.execute(f"UPDATE mantpred.usuarios SET {', '.join(cambios)} WHERE id = %s RETURNING email",
                    (*valores, usuario_id))
        fila = cur.fetchone()
        if fila is None:
            raise HTTPException(404, "Usuario no encontrado")
        detalle = []
        if datos.rol is not None:
            detalle.append(f"rol {datos.rol}")
        if datos.activo is not None:
            detalle.append("activado" if datos.activo else "desactivado")
        if datos.nombre is not None:
            detalle.append("nombre actualizado")
        auditar(cur, admin["id"], admin["email"], ip_cliente(request), "usuario_modificado",
                f"{fila['email']}: {', '.join(detalle)}")
        cur.execute(_SELECT + " WHERE u.id = %s", (usuario_id,))
        return cur.fetchone()


@router.post("/{usuario_id}/restablecer-clave", summary="Asignar una contraseña temporal y desbloquear")
def restablecer_clave(usuario_id: int, datos: ClaveTemporal, request: Request,
                      admin: dict = Depends(solo_admin)):
    validar_clave_nueva(datos.clave_temporal)
    with cursor() as cur:
        cur.execute(
            """UPDATE mantpred.usuarios SET password_hash = %s, debe_cambiar_clave = TRUE,
                      intentos_fallidos = 0, bloqueado_hasta = NULL
               WHERE id = %s RETURNING email""", (hash_clave(datos.clave_temporal), usuario_id))
        fila = cur.fetchone()
        if fila is None:
            raise HTTPException(404, "Usuario no encontrado")
        auditar(cur, admin["id"], admin["email"], ip_cliente(request), "clave_restablecida", fila["email"])
    return {"mensaje": f"Contraseña temporal asignada a {fila['email']}; deberá cambiarla al ingresar"}


@router.get("/auditoria", summary="Últimos registros de acceso")
def auditoria(limite: int = Query(100, ge=1, le=1000), admin: dict = Depends(solo_admin)):
    with cursor() as cur:
        cur.execute(
            """SELECT a.fecha, a.email, host(a.ip) AS ip, a.accion, a.detalle
               FROM mantpred.auditoria_accesos a ORDER BY a.fecha DESC LIMIT %s""", (limite,))
        return cur.fetchall()
