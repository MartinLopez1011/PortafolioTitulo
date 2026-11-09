"""Crea (o actualiza) un administrador real y desactiva los usuarios de prueba @demo.qla.cl.

Ejecutar ANTES de publicar el servidor: la clave de los usuarios de prueba está en el repositorio.

    python crear_admin.py --env C:\\Users\\nicol\\qla_rds.env

Pide nombre, correo y clave por teclado (la clave no se muestra ni se guarda en ningún archivo).
"""
import argparse
import getpass
import re
import sys
from pathlib import Path

import psycopg

from ejecutar_sql import leer_url


def main() -> None:
    ap = argparse.ArgumentParser(description="Crea el administrador real y desactiva los de prueba")
    ap.add_argument("--env", default=str(Path(__file__).with_name(".env")), help="archivo con DATABASE_URL")
    ap.add_argument("--mantener-demo", action="store_true", help="no desactivar los usuarios @demo.qla.cl")
    args = ap.parse_args()

    nombre = input("Nombre completo: ").strip()
    email = input("Correo: ").strip().lower()
    if not nombre or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        sys.exit("Nombre o correo no válido")
    clave = getpass.getpass("Clave (mín. 10 caracteres, se escribe sin mostrarse): ")
    if len(clave) < 10 or clave != getpass.getpass("Repite la clave: "):
        sys.exit("La clave es muy corta o no coincide")

    with psycopg.connect(leer_url(Path(args.env)), connect_timeout=20) as con, con.cursor() as cur:
        cur.execute("SET search_path TO mantpred, extensions, public")
        cur.execute(
            """INSERT INTO usuarios (rol_id, nombre, email, password_hash, debe_cambiar_clave)
               VALUES ((SELECT id FROM roles WHERE nombre = 'administrador'), %s, %s,
                       crypt(%s, gen_salt('bf', 12)), false)
               ON CONFLICT (lower(email)) DO UPDATE
                   SET nombre = EXCLUDED.nombre, password_hash = EXCLUDED.password_hash,
                       rol_id = EXCLUDED.rol_id, activo = true, debe_cambiar_clave = false,
                       intentos_fallidos = 0, bloqueado_hasta = NULL
               RETURNING id""", (nombre, email, clave))
        uid = cur.fetchone()[0]
        desactivados = 0
        if not args.mantener_demo:
            cur.execute("UPDATE usuarios SET activo = false WHERE email ILIKE '%%@demo.qla.cl' AND activo")
            desactivados = cur.rowcount
    print(f"Administrador listo (id {uid}, {email}). Usuarios de prueba desactivados: {desactivados}")


if __name__ == "__main__":
    main()
