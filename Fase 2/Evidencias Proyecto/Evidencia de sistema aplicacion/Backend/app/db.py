"""Conexión a PostgreSQL (Supabase) con un pool de conexiones."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None


def abrir() -> None:
    global _pool
    _pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=5,                      # el plan gratis de Supabase limita las conexiones
        timeout=15,
        open=True,
        kwargs={"row_factory": dict_row,
                "prepare_threshold": None,   # necesario con el pooler de Supabase
                "connect_timeout": 15},
    )


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
