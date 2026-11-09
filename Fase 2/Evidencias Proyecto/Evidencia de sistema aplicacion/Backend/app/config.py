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


def _si(nombre: str) -> bool:
    return os.environ.get(nombre, "").strip().lower() in ("1", "true", "si", "sí", "yes")


DATABASE_URL = os.environ.get("DATABASE_URL", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_MINUTOS = int(os.environ.get("JWT_MINUTOS", "480"))          # duración de la sesión (8 h)
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5500").split(",") if o.strip()]

# Clave que deben enviar el simulador, el Edge Gateway o la Lambda de persistencia
# en el encabezado X-Clave-Ingesta. Sin clave configurada, la ingesta queda cerrada.
CLAVE_INGESTA = os.environ.get("CLAVE_INGESTA", "")

# Modo demostración: datos de ejemplo en memoria, sin base de datos.
# Solo se activa si se pide explícitamente (MODO_DEMO=1) y exige DEMO_CLAVE para entrar.
MODO_DEMO = _si("MODO_DEMO")
DEMO_CLAVE = os.environ.get("DEMO_CLAVE", "")

EQUIPO_POR_DEFECTO = "MC-01"
# Identificador que usa la Lambda de inferencia para el mismo equipo
ALIAS_EQUIPO = {"MOLINO_QLA_01": "MC-01"}
ZONA_HORARIA = "America/Santiago"   # los "días" del dashboard son días de la planta
# Simulador controlable (HU-17 a HU-19). En EC2 todo se obtiene del rol de la instancia.
SIM_PUBLICAR = os.environ.get("SIM_PUBLICAR", "iot").strip().lower()   # iot | local
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT", "")      # vacío: se consulta a AWS
SIM_BUCKET = os.environ.get("SIM_BUCKET", "")          # vacío: el de la Lambda de inferencia
SIM_DATASET = os.environ.get("SIM_DATASET", "")        # vacío: carpeta del repo o S3
MAX_INTENTOS = 5          # intentos fallidos antes de bloquear la cuenta
MINUTOS_BLOQUEO = 15


def validar() -> None:
    errores = []
    if not DATABASE_URL and not MODO_DEMO:
        errores.append("Falta DATABASE_URL en el archivo .env (o MODO_DEMO=1 para usar datos de ejemplo)")
    if MODO_DEMO and len(DEMO_CLAVE) < 8:
        errores.append("MODO_DEMO=1 requiere DEMO_CLAVE con al menos 8 caracteres")
    if len(JWT_SECRET) < 32:
        errores.append('JWT_SECRET debe tener al menos 32 caracteres. Genera uno con:\n'
                       '    python -c "import secrets; print(secrets.token_urlsafe(48))"')
    if CLAVE_INGESTA and len(CLAVE_INGESTA) < 24:
        errores.append("CLAVE_INGESTA debe tener al menos 24 caracteres (genérala igual que JWT_SECRET)")
    if errores:
        raise RuntimeError("Configuración incompleta:\n- " + "\n- ".join(errores))
