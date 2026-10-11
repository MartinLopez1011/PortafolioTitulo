#!/usr/bin/env python3
"""
cargar_datos.py - Carga el dataset simulado del molino MC-01 en Supabase.

Qué hace
  1. Lee Dataset_Molino_QLA_Realista (.zip o .csv) y se queda con una ventana
     de N días (por defecto 14 días desde 2026-05-27, que incluye 6 de las 7
     fallas del modelo).
  2. Convierte las 41 columnas de sensores a formato largo (una fila por
     sensor y minuto) y las inserta en mantpred.lecturas con fuente='simulado'.
  3. Inserta el estado de operación y el tipo de asfalto de cada minuto en
     mantpred.estados_equipo.
  4. La columna LABEL_Estado_Planta (la falla "verdadera" del simulador) NO se
     carga: en una planta real no existe.

Es seguro ejecutarlo varias veces: las filas que ya existen se omiten
(ON CONFLICT DO NOTHING). Se carga un día a la vez, así que si se corta
se puede volver a correr y continúa.

Uso
  python cargar_datos.py --csv RUTA/Dataset_Molino_QLA_Realista.zip --dry-run
  python cargar_datos.py --csv RUTA/Dataset_Molino_QLA_Realista.zip
  python cargar_datos.py --csv RUTA/... --inicio 2026-09-19 --dias 14
  python cargar_datos.py --csv RUTA/... --reemplazar      (borra lo simulado antes)

Conexión
  Define DATABASE_URL en un archivo .env (no se sube al repositorio):
    DATABASE_URL=postgresql://postgres.xxxx:CLAVE@aws-0-REGION.pooler.supabase.com:5432/postgres
  Usa la cadena "Session pooler" de Supabase (Connect > Session pooler).

Dependencias: pandas y psycopg  ->  pip install pandas "psycopg[binary]"
"""
import argparse
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd

SCHEMA = "mantpred"
ZONA_PLANTA = "America/Santiago"
COLS_NO_SENSOR = {"timestamp", "ESTADO_operacion", "TIPO_asfalto", "LABEL_Estado_Planta"}
BYTES_POR_LECTURA = 170          # medido: 826.560 lecturas = 140 MB con índices
LIMITE_PLAN_FREE_MB = 500
AVISO_MB = 350


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def cargar_env(ruta: str = ".env") -> None:
    """Lee KEY=VALOR de un .env sin pisar variables ya definidas."""
    p = Path(ruta)
    if not p.exists():
        return
    for linea in p.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def n(x: int) -> str:
    return f"{x:,}".replace(",", ".")


# ----------------------------------------------------------------------
# Lectura y preparación (no necesita base de datos)
# ----------------------------------------------------------------------
def leer_ventana(ruta: str, inicio: pd.Timestamp, dias: int) -> pd.DataFrame:
    p = Path(ruta)
    if not p.exists():
        fail(f"no existe el archivo {ruta}")
    fin = inicio + pd.Timedelta(days=dias)
    trozos = []
    # Se lee por trozos para no cargar los 525.600 minutos completos en memoria
    for chunk in pd.read_csv(p, parse_dates=["timestamp"], chunksize=100_000):
        sel = chunk[(chunk["timestamp"] >= inicio) & (chunk["timestamp"] < fin)]
        if not sel.empty:
            trozos.append(sel)
    if not trozos:
        fail(f"el dataset no tiene datos entre {inicio.date()} y {fin.date()} "
             "(cubre 2026-01-01 a 2026-12-31)")
    df = pd.concat(trozos, ignore_index=True)

    # El dataset trae hora de planta sin zona horaria: se interpreta como hora de Chile
    ts = df["timestamp"].dt.tz_localize(ZONA_PLANTA, ambiguous="NaT", nonexistent="shift_forward")
    df["ts"] = ts.dt.tz_convert("UTC")
    df = df.dropna(subset=["ts"]).drop_duplicates(subset="ts")
    df["dia"] = df["timestamp"].dt.date
    return df


def columnas_sensor(df: pd.DataFrame) -> list:
    return [c for c in df.columns if c not in COLS_NO_SENSOR and c not in ("ts", "dia")]


def resumen(df: pd.DataFrame, sens: list) -> None:
    filas_lect = len(df) * len(sens)
    mb = filas_lect * BYTES_POR_LECTURA / 1e6
    print(f"  Ventana      : {df['timestamp'].min()}  ->  {df['timestamp'].max()}")
    print(f"  Minutos      : {n(len(df))}  ({df['dia'].nunique()} días)")
    print(f"  Sensores     : {len(sens)}")
    print(f"  Lecturas     : {n(filas_lect)}  (≈ {mb:.0f} MB en la base)")
    print("  Estados      :", df["ESTADO_operacion"].value_counts().to_dict())
    fallas = df.loc[df["LABEL_Estado_Planta"] != "Normal", "LABEL_Estado_Planta"].value_counts()
    print("  Fallas (solo informativo, no se cargan):")
    for k, v in fallas.items():
        print(f"      {k}: {n(int(v))} min")
    if mb > AVISO_MB:
        print(f"  AVISO: supera {AVISO_MB} MB; el plan gratis permite {LIMITE_PLAN_FREE_MB} MB.")


def lecturas_largo(dia_df: pd.DataFrame, sens: list) -> pd.DataFrame:
    largo = dia_df.melt(id_vars="ts", value_vars=sens, var_name="tag", value_name="valor")
    largo["valor"] = largo["valor"].round(3)
    return largo


def estados_equipo(dia_df: pd.DataFrame) -> pd.DataFrame:
    e = dia_df[["ts"]].copy()
    e["estado"] = dia_df["ESTADO_operacion"].str.lower()
    e["tipo_asfalto"] = dia_df["TIPO_asfalto"].str.lower()
    return e


# ----------------------------------------------------------------------
# Carga en la base
# ----------------------------------------------------------------------
def copiar(cur, tabla_sql: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    with cur.copy(tabla_sql) as cp:
        cp.write(buf.getvalue())


def cargar(df: pd.DataFrame, sens: list, equipo: str, reemplazar: bool) -> None:
    try:
        import psycopg
    except ImportError:
        fail('falta la librería psycopg. Instálala con:  pip install "psycopg[binary]"')

    url = os.environ.get("DATABASE_URL")
    if not url:
        fail("no está definida DATABASE_URL (ponla en el archivo .env)")

    print("\nConectando a la base...")
    with psycopg.connect(url, connect_timeout=20) as conn:
        conn.prepare_threshold = None   # necesario si se usa el pooler de Supabase
        cur = conn.cursor()
        cur.execute(f"SET search_path TO {SCHEMA}, public")

        cur.execute("SELECT id FROM equipos WHERE codigo = %s", (equipo,))
        fila = cur.fetchone()
        if not fila:
            fail(f"no existe el equipo {equipo} en la tabla equipos")
        equipo_id = fila[0]

        cur.execute("SELECT tag, id FROM sensores WHERE equipo_id = %s AND origen = 'simulado'",
                    (equipo_id,))
        mapa = dict(cur.fetchall())
        faltan = [s for s in sens if s not in mapa]
        if faltan:
            fail("estas columnas del dataset no tienen sensor simulado en la base: "
                 + ", ".join(faltan))

        if reemplazar:
            resp = input("Se borrarán TODAS las lecturas y estados simulados. Escribe SI para continuar: ")
            if resp.strip() != "SI":
                fail("cancelado por el usuario")
            cur.execute("DELETE FROM lecturas WHERE fuente = 'simulado'")
            cur.execute("DELETE FROM estados_equipo WHERE fuente = 'simulado' AND equipo_id = %s",
                        (equipo_id,))
            conn.commit()
            print("  Datos simulados anteriores borrados.")

        cur.execute("""CREATE TEMP TABLE tmp_lect (sensor_id integer, ts timestamptz, valor numeric(12,3))
                       ON COMMIT DELETE ROWS""")
        cur.execute("""CREATE TEMP TABLE tmp_est (ts timestamptz, estado varchar(15), tipo_asfalto varchar(15))
                       ON COMMIT DELETE ROWS""")
        conn.commit()

        t0 = time.time()
        tot_lect = tot_est = 0
        for dia, dia_df in df.groupby("dia"):
            largo = lecturas_largo(dia_df, sens)
            largo["sensor_id"] = largo["tag"].map(mapa)
            copiar(cur, "COPY tmp_lect (sensor_id, ts, valor) FROM STDIN WITH (FORMAT csv)",
                   largo[["sensor_id", "ts", "valor"]])
            cur.execute("""INSERT INTO lecturas (sensor_id, ts, valor, calidad, fuente)
                           SELECT sensor_id, ts, valor, 'buena', 'simulado' FROM tmp_lect
                           ON CONFLICT (sensor_id, fuente, ts) DO NOTHING""")
            nuevas_l = cur.rowcount

            copiar(cur, "COPY tmp_est (ts, estado, tipo_asfalto) FROM STDIN WITH (FORMAT csv)",
                   estados_equipo(dia_df))
            cur.execute("""INSERT INTO estados_equipo (equipo_id, ts, estado, tipo_asfalto, fuente)
                           SELECT %s, ts, estado, tipo_asfalto, 'simulado' FROM tmp_est
                           ON CONFLICT (equipo_id, fuente, ts) DO NOTHING""", (equipo_id,))
            nuevas_e = cur.rowcount
            conn.commit()
            tot_lect += nuevas_l
            tot_est += nuevas_e
            print(f"  {dia}: lecturas nuevas {n(nuevas_l):>8}  |  estados nuevos {n(nuevas_e):>6}")

        print(f"\nListo en {time.time() - t0:.0f} s. Nuevas: {n(tot_lect)} lecturas, {n(tot_est)} estados.")
        if tot_lect == 0:
            print("(No se insertó nada: esa ventana ya estaba cargada.)")

        # Verificación y tamaño
        cur.execute("SELECT fuente, count(*), min(ts), max(ts) FROM lecturas GROUP BY fuente ORDER BY 1")
        print("\nContenido actual de lecturas:")
        for fuente, cnt, mn, mx in cur.fetchall():
            print(f"  {fuente:9} {n(cnt):>12} filas   {mn:%Y-%m-%d %H:%M} -> {mx:%Y-%m-%d %H:%M} (UTC)")
        cur.execute("SELECT pg_total_relation_size('lecturas'), pg_database_size(current_database())")
        t_lect, t_bd = cur.fetchone()
        print(f"\nTabla lecturas : {t_lect / 1e6:.0f} MB")
        print(f"Base completa  : {t_bd / 1e6:.0f} MB de {LIMITE_PLAN_FREE_MB} MB del plan gratis")
        if t_bd / 1e6 > AVISO_MB:
            print("AVISO: te acercas al límite. Usa:  SELECT mantpred.purgar_lecturas_simuladas(14);")


# ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Carga el dataset simulado MC-01 en Supabase")
    ap.add_argument("--csv", required=True, help="ruta al .zip o .csv del dataset")
    ap.add_argument("--inicio", default="2026-05-27", help="primer día a cargar (AAAA-MM-DD)")
    ap.add_argument("--dias", type=int, default=14, help="cantidad de días (por defecto 14)")
    ap.add_argument("--equipo", default="MC-01", help="código del equipo (por defecto MC-01)")
    ap.add_argument("--dry-run", action="store_true", help="solo muestra qué se cargaría")
    ap.add_argument("--reemplazar", action="store_true", help="borra lo simulado antes de cargar")
    ap.add_argument("--env", default=".env", help="archivo con DATABASE_URL")
    ap.add_argument("--solo-csv", metavar="CARPETA",
                    help="no usa la base: escribe lecturas.csv y estados.csv en esa carpeta")
    a = ap.parse_args()

    cargar_env(a.env)
    inicio = pd.Timestamp(a.inicio)
    print(f"Leyendo {a.csv} ...")
    df = leer_ventana(a.csv, inicio, a.dias)
    sens = columnas_sensor(df)
    print("\nVentana seleccionada")
    resumen(df, sens)

    if a.solo_csv:
        out = Path(a.solo_csv)
        out.mkdir(parents=True, exist_ok=True)
        largo = pd.concat([lecturas_largo(d, sens) for _, d in df.groupby("dia")])
        largo.to_csv(out / "lecturas.csv", index=False)
        estados_equipo(df).to_csv(out / "estados.csv", index=False)
        print(f"\nCSV escritos en {out}")
        return
    if a.dry_run:
        print("\n(dry-run: no se escribió nada en la base)")
        return
    cargar(df, sens, a.equipo, a.reemplazar)


if __name__ == "__main__":
    main()
