"""Inicio de sesión, datos del usuario y cambio de contraseña."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import config
from ..db import cursor
from ..seguridad import (HASH_RELLENO, auditar, crear_token, hash_clave, ip_cliente, usuario_actual,
                         validar_clave_nueva, verificar_clave)

router = APIRouter(prefix="/auth", tags=["Autenticación"])

CREDENCIALES_INVALIDAS = "Correo o contraseña incorrectos"


class LoginEntrada(BaseModel):
    email: str = Field(min_length=3, max_length=150, examples=["admin@demo.qla.cl"])
    clave: str = Field(min_length=1, max_length=72, examples=["Qla.2026!"])


class CambioClave(BaseModel):
    clave_actual: str = Field(min_length=1, max_length=72)
    clave_nueva: str = Field(min_length=8, max_length=72)


@router.post("/login", summary="Iniciar sesión y obtener un token")
def login(datos: LoginEntrada, request: Request):
    ip = ip_cliente(request)
    email = datos.email.strip().lower()
    error = None          # se lanza al final, después del COMMIT, para no perder el registro

    with cursor() as cur:
        cur.execute(
            """SELECT u.id, u.nombre, u.email, u.password_hash, u.activo, u.debe_cambiar_clave,
                      u.intentos_fallidos, u.bloqueado_hasta > now() AS bloqueado,
                      r.nombre AS rol, r.nivel
               FROM mantpred.usuarios u JOIN mantpred.roles r ON r.id = u.rol_id
               WHERE lower(u.email) = %s""", (email,))
        u = cur.fetchone()

        if u is None:
            verificar_clave(datos.clave, HASH_RELLENO)
            auditar(cur, None, email, ip, "login_fallido", "usuario no existe")
            error = (status.HTTP_401_UNAUTHORIZED, CREDENCIALES_INVALIDAS)
        elif not u["activo"]:
            auditar(cur, u["id"], email, ip, "login_rechazado", "usuario inactivo")
            error = (status.HTTP_401_UNAUTHORIZED, CREDENCIALES_INVALIDAS)
        elif u["bloqueado"]:
            auditar(cur, u["id"], email, ip, "login_bloqueado", "cuenta bloqueada temporalmente")
            error = (status.HTTP_423_LOCKED,
                     f"Cuenta bloqueada por intentos fallidos. Intente en {config.MINUTOS_BLOQUEO} minutos.")
        elif not verificar_clave(datos.clave, u["password_hash"]):
            intentos = u["intentos_fallidos"] + 1
            if intentos >= config.MAX_INTENTOS:
                cur.execute(
                    """UPDATE mantpred.usuarios SET intentos_fallidos = 0,
                              bloqueado_hasta = now() + make_interval(mins => %s) WHERE id = %s""",
                    (config.MINUTOS_BLOQUEO, u["id"]))
                auditar(cur, u["id"], email, ip, "login_fallido", f"clave incorrecta; cuenta bloqueada")
                error = (status.HTTP_423_LOCKED,
                         f"Demasiados intentos. Cuenta bloqueada por {config.MINUTOS_BLOQUEO} minutos.")
            else:
                cur.execute("UPDATE mantpred.usuarios SET intentos_fallidos = %s WHERE id = %s",
                            (intentos, u["id"]))
                auditar(cur, u["id"], email, ip, "login_fallido", f"clave incorrecta ({intentos})")
                error = (status.HTTP_401_UNAUTHORIZED, CREDENCIALES_INVALIDAS)
        else:
            cur.execute(
                """UPDATE mantpred.usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL,
                          ultimo_acceso = now() WHERE id = %s""", (u["id"],))
            auditar(cur, u["id"], email, ip, "login_ok")

    if error:
        raise HTTPException(error[0], error[1])
    return {
        "access_token": crear_token(u),
        "token_type": "bearer",
        "expira_en_segundos": config.JWT_MINUTOS * 60,
        "usuario": {k: u[k] for k in ("id", "nombre", "email", "rol", "nivel", "debe_cambiar_clave")},
    }


@router.get("/me", summary="Datos del usuario que inició sesión")
def me(u: dict = Depends(usuario_actual)):
    return u


@router.post("/cambiar-clave", summary="Cambiar la contraseña propia")
def cambiar_clave(datos: CambioClave, request: Request, u: dict = Depends(usuario_actual)):
    validar_clave_nueva(datos.clave_nueva)
    if datos.clave_nueva == datos.clave_actual:
        raise HTTPException(422, "La contraseña nueva debe ser distinta de la actual")
    error = None
    with cursor() as cur:
        cur.execute("SELECT password_hash FROM mantpred.usuarios WHERE id = %s", (u["id"],))
        if not verificar_clave(datos.clave_actual, cur.fetchone()["password_hash"]):
            auditar(cur, u["id"], u["email"], ip_cliente(request), "cambio_clave_fallido")
            error = "La contraseña actual no es correcta"
        else:
            cur.execute(
                """UPDATE mantpred.usuarios SET password_hash = %s, debe_cambiar_clave = FALSE
                   WHERE id = %s""", (hash_clave(datos.clave_nueva), u["id"]))
            auditar(cur, u["id"], u["email"], ip_cliente(request), "cambio_clave")
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    return {"mensaje": "Contraseña actualizada"}
