"""Muestra qué hay en la base (RDS) y si está recibiendo datos en este momento.

    python verificar_bd.py --env "%USERPROFILE%\\qla_rds_aws.env"
    python verificar_bd.py --env "$HOME\\qla_rds_aws.env" --vigilar 30   # repite cada 30 s

Solo lee (SELECT): no modifica nada. No muestra la contraseña.
"""
import argparse
import sys
import time
from pathlib import Path

import psycopg

TABLAS = ["equipos", "componentes", "sensores", "rangos_operacion", "tipos_falla", "reglas_alarma",
          "roles", "usuarios", "auditoria_accesos", "mantenimientos", "mantenimiento_fallas",
          "lecturas", "estados_equipo", "predicciones", "condiciones_minuto", "alarmas"]


def leer_url(ruta: Path) -> str:
    if not ruta.exists():
        sys.exit(f"No existe {ruta}")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("DATABASE_URL="):
            return linea.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{ruta} no tiene DATABASE_URL")


def informe(cur) -> dict:
    cur.execute("SELECT now(), inet_server_addr(), version()")
    ahora, ip, version = cur.fetchone()
    print(f"\nServidor: {ip}  |  {version.split(',')[0]}  |  hora de la base: {ahora:%Y-%m-%d %H:%M:%S %Z}")
    print(f"\n{'Tabla':<22}{'Filas':>10}")
    conteos = {}
    for t in TABLAS:
        cur.execute(f"SELECT count(*) FROM mantpred.{t}")
        conteos[t] = cur.fetchone()[0]
        print(f"{t:<22}{conteos[t]:>10,}".replace(",", "."))

    print("\nÚltimos datos guardados por el flujo (fecha simulada, en UTC):")
    cur.execute("""SELECT max(ts) FROM mantpred.lecturas WHERE fuente = 'simulado'""")
    print(f"  Última lectura simulada ........ {cur.fetchone()[0]}")
    cur.execute("""SELECT modelo, max(ts), count(*) FROM mantpred.predicciones GROUP BY modelo ORDER BY modelo""")
    for modelo, ts, n in cur.fetchall():
        print(f"  Predicciones {modelo:<12} ...... {n:>6} filas, última {ts}")
    cur.execute("""SELECT count(*) FILTER (WHERE fin IS NULL), count(*) FROM mantpred.alarmas""")
    activas, total = cur.fetchone()
    print(f"  Alarmas ......................... {activas} activas de {total}")
    cur.execute("""SELECT s.tag, l.valor, l.ts FROM mantpred.lecturas l JOIN mantpred.sensores s ON s.id = l.sensor_id
                   WHERE s.tag IN ('RPM_motor_molino', 'AMP_vfd_motor_molino', 'CAU_bomba_lpm', 'PRE_dif_filtro_bar')
                     AND l.ts = (SELECT max(ts) FROM mantpred.lecturas WHERE fuente = 'simulado')
                   ORDER BY s.tag""")
    filas = cur.fetchall()
    if filas:
        print("\n  Valores del último minuto (compáralos con el dashboard):")
        for tag, valor, _ in filas:
            print(f"    {tag:<24} {valor}")
    return conteos


def main() -> None:
    ap = argparse.ArgumentParser(description="Revisa el contenido de la base del proyecto (solo lectura)")
    ap.add_argument("--env", default=str(Path.home() / "qla_rds_aws.env"), help="archivo con DATABASE_URL")
    ap.add_argument("--vigilar", type=int, default=0, help="segundos entre revisiones (0 = una sola vez)")
    args = ap.parse_args()
    url = leer_url(Path(args.env))
    print("Conectando a", url.split("@")[-1].split("?")[0], "...")
    with psycopg.connect(url, connect_timeout=20, autocommit=True) as con, con.cursor() as cur:
        anterior = informe(cur)
        while args.vigilar:
            time.sleep(args.vigilar)
            actual = informe(cur)
            print(f"\nEn los últimos {args.vigilar} s se guardaron: "
                  f"{actual['lecturas'] - anterior['lecturas']} lecturas, "
                  f"{actual['predicciones'] - anterior['predicciones']} predicciones")
            anterior = actual


if __name__ == "__main__":
    main()
