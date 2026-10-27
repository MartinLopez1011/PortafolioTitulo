"""Conexión a PostgreSQL (Supabase) con un pool de conexiones y fallback automático a modo demostración."""
from contextlib import contextmanager
import logging
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
MODO_DEMO: bool = False


def abrir() -> None:
    global _pool, MODO_DEMO
    # Si la URL es la de ejemplo o localhost por defecto, activar modo demostración sin esperar timeout
    if not config.DATABASE_URL or "TU_PROJECT_REF" in config.DATABASE_URL or "localhost" in config.DATABASE_URL:
        logger.info("DATABASE_URL no configurada para Supabase remoto. Activando modo demostración local.")
        MODO_DEMO = True
        _pool = None
        return

    try:
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=3,
            open=True,
            kwargs={"row_factory": dict_row,
                    "prepare_threshold": None,
                    "connect_timeout": 3},
        )
        MODO_DEMO = False
        logger.info("Conexión exitosa al pool de base de datos PostgreSQL/Supabase.")
    except Exception as e:
        logger.warning(f"No se pudo conectar a PostgreSQL/Supabase ({e}). Activando modo demostración local.")
        MODO_DEMO = True
        _pool = None


def cerrar() -> None:
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            pass


@contextmanager
def cursor():
    """Entrega un cursor dentro de una transacción.
    Si el bloque termina bien se hace COMMIT; si lanza una excepción, ROLLBACK."""
    if _pool is None:
        raise RuntimeError("El pool de conexiones no está abierto (modo demostración activo)")
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur
