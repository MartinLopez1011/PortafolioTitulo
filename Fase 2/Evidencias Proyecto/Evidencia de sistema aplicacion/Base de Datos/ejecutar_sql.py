"""Ejecuta un archivo .sql completo en la base indicada en DATABASE_URL (.env).

Sirve para crear el esquema y aplicar migraciones sin instalar psql:

    python ejecutar_sql.py bd_mantenimiento_predictivo_v2.sql
    python ejecutar_sql.py migracion_v3.sql

Opciones:
    --env RUTA   archivo con DATABASE_URL (por defecto .env de esta carpeta)
"""
import argparse
import sys
import time
from pathlib import Path

import psycopg


def leer_url(ruta_env: Path) -> str:
    if not ruta_env.exists():
        sys.exit(f"No existe {ruta_env}. Crea el archivo con la línea DATABASE_URL=...")
    for linea in ruta_env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea.startswith("DATABASE_URL="):
            return linea.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{ruta_env} no tiene la línea DATABASE_URL=...")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ejecuta un archivo SQL en la base del proyecto")
    ap.add_argument("archivo", help="archivo .sql a ejecutar")
    ap.add_argument("--env", default=str(Path(__file__).with_name(".env")), help="archivo con DATABASE_URL")
    args = ap.parse_args()

    sql = Path(args.archivo).read_text(encoding="utf-8")
    url = leer_url(Path(args.env))
    destino = url.split("@")[-1].split("?")[0]          # servidor y base, sin usuario ni clave
    print(f"Ejecutando {args.archivo} en {destino} ...")
    t0 = time.time()
    try:
        # autocommit: el propio archivo maneja BEGIN/COMMIT; sin parámetros, psycopg acepta
        # varias sentencias en una sola llamada.
        with psycopg.connect(url, autocommit=True, connect_timeout=20) as con:
            con.execute(sql)
    except psycopg.Error as e:
        # El mensaje de PostgreSQL no incluye la contraseña
        sys.exit(f"ERROR al ejecutar {args.archivo}:\n{e}")
    print(f"Listo en {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
