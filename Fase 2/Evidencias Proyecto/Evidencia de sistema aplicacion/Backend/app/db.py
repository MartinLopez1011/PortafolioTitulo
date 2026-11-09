"""Conexión a PostgreSQL (Supabase) con un pool de conexiones.

El modo demostración (datos de ejemplo en memoria) se activa solo con MODO_DEMO=1 en el .env.
Si la base no responde, la API contesta 503 y se recupera sola cuando la base vuelve:
nunca cambia por su cuenta a datos de ejemplo.
"""
import logging
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
MODO_DEMO: bool = config.MODO_DEMO


def abrir() -> None:
    global _pool
    if MODO_DEMO:
        logger.warning("MODO_DEMO=1: la API usa datos de ejemplo en memoria, sin base de datos.")
        return
    _pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=5,                      # el plan gratis de Supabase limita las conexiones
        timeout=15,
        open=False,
        kwargs={"row_factory": dict_row,
                "prepare_threshold": None,   # necesario con el pooler de Supabase
                "connect_timeout": 15},
    )
    # open(wait=False): la API arranca aunque la base esté pausada; las consultas
    # responden 503 hasta que la base vuelva.
    _pool.open(wait=False)


def cerrar() -> None:
    if _pool is not None:
        _pool.close()


@contextmanager
def cursor():
    """Entrega un cursor dentro de una transacción.
    Si el bloque termina bien se hace COMMIT; si lanza una excepción, ROLLBACK."""
    if _pool is None:
        raise RuntimeError("El pool de conexiones no está abierto")
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur
