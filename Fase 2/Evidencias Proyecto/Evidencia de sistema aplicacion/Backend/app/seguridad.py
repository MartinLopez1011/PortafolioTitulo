"""Contraseñas (bcrypt), tokens de sesión (JWT) y control de acceso por rol."""
import datetime as dt
import ipaddress
import re

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .db import cursor

# Niveles de acceso (igual que la tabla mantpred.roles)
VISUALIZADOR, OPERADOR, SUPERVISOR, ADMINISTRADOR = 1, 2, 3, 4

_bearer = HTTPBearer(auto_error=False, description="Token obtenido en /api/auth/login")


# ---------------------------------------------------------------- contraseñas
def hash_clave(clave: str) -> str:
    return bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def verificar_clave(clave: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(clave.encode("utf-8"), hash_guardado.encode("ascii"))
    except ValueError:
        return False


# Hash de relleno: si el usuario no existe igual se verifica una clave,
# para que el tiempo de respuesta no revele qué correos están registrados.
HASH_RELLENO = hash_clave("relleno-sin-uso")


def validar_clave_nueva(clave: str) -> None:
    if not (8 <= len(clave) <= 72):
        raise HTTPException(422, "La contraseña debe tener entre 8 y 72 caracteres")
    if not re.search(r"[A-Za-z]", clave) or not re.search(r"\d", clave):
        raise HTTPException(422, "La contraseña debe incluir letras y números")


# ---------------------------------------------------------------- tokens
def crear_token(usuario: dict) -> str:
    ahora = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(usuario["id"]),
        "rol": usuario["rol"],
        "nivel": usuario["nivel"],
        "iat": ahora,
        "exp": ahora + dt.timedelta(minutes=config.JWT_MINUTOS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def _no_autorizado(detalle: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detalle, headers={"WWW-Authenticate": "Bearer"})


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Usuario dueño del token. Se consulta la base en cada petición, así un usuario
    desactivado o con cambio de rol pierde el acceso de inmediato."""
    if cred is None:
        raise _no_autorizado("Debe iniciar sesión")
    try:
        datos = jwt.decode(cred.credentials, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise _no_autorizado("La sesión expiró; inicie sesión nuevamente")
    except jwt.InvalidTokenError:
        raise _no_autorizado("Token inválido")
    with cursor() as cur:
        cur.execute(
            """SELECT u.id, u.nombre, u.email, u.activo, u.debe_cambiar_clave, r.nombre AS rol, r.nivel
               FROM mantpred.usuarios u JOIN mantpred.roles r ON r.id = u.rol_id
               WHERE u.id = %s""", (int(datos["sub"]),))
        u = cur.fetchone()
    if u is None or not u["activo"]:
        raise _no_autorizado("Usuario no habilitado")
    return u


def usuario_habilitado(u: dict = Depends(usuario_actual)) -> dict:
    """Igual que usuario_actual, pero exige haber cambiado la contraseña inicial."""
    if u["debe_cambiar_clave"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Debe cambiar su contraseña antes de continuar (POST /api/auth/cambiar-clave)")
    return u


def requiere_nivel(nivel: int):
    """Dependencia que permite el acceso solo a roles con nivel >= nivel."""
    def _dep(u: dict = Depends(usuario_habilitado)) -> dict:
        if u["nivel"] < nivel:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no tiene permiso para esta acción")
        return u
    return _dep


# ---------------------------------------------------------------- auditoría
def ip_cliente(request: Request) -> str | None:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "")
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def auditar(cur, usuario_id: int | None, email: str | None, ip: str | None, accion: str,
            detalle: str | None = None) -> None:
    cur.execute(
        """INSERT INTO mantpred.auditoria_accesos (usuario_id, email, ip, accion, detalle)
           VALUES (%s, %s, %s, %s, %s)""",
        (usuario_id, (email or "")[:150] or None, ip, accion[:50], (detalle or "")[:250] or None))
