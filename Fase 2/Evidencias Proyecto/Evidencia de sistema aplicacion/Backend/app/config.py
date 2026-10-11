"""Configuración del backend. Los valores secretos se leen del archivo .env."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env(ruta: Path) -> None:
    """Lee KEY=VALOR de un .env sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_cargar_env(RAIZ / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_MINUTOS = int(os.environ.get("JWT_MINUTOS", "480"))          # duración de la sesión (8 h)
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5500").split(",") if o.strip()]

EQUIPO_POR_DEFECTO = "MC-01"
MAX_INTENTOS = 5          # intentos fallidos antes de bloquear la cuenta
MINUTOS_BLOQUEO = 15


def validar() -> None:
    errores = []
    if not DATABASE_URL:
        errores.append("Falta DATABASE_URL en el archivo .env")
    if len(JWT_SECRET) < 32:
        errores.append('JWT_SECRET debe tener al menos 32 caracteres. Genera uno con:\n'
                       '    python -c "import secrets; print(secrets.token_urlsafe(48))"')
    if errores:
        raise RuntimeError("Configuración incompleta:\n- " + "\n- ".join(errores))
