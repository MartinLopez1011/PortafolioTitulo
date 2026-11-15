"""Comprueba que el esquema instalado en la base (Amazon RDS) sea igual al de bd_mantpred_v4_1_completo.sql.

    python verificar_esquema.py --env "$HOME\\qla_rds_aws.env"

Compara tablas, columnas (tipo, nulos, valor por defecto), restricciones (PK, FK, UNIQUE, CHECK),
índices, funciones, triggers, RLS y los datos de catálogo contra esquema_v4_1_referencia.json.
Solo lee (SELECT): no modifica nada y no muestra la contraseña.

Regenerar la referencia (solo si cambia el SQL), desde una base creada con ese SQL:
    python verificar_esquema.py --env base_local.env --generar-referencia
"""
import argparse
import json
import re
import sys
from pathlib import Path

import psycopg

ESQUEMA = "mantpred"
REFERENCIA = Path(__file__).with_name("esquema_v4_1_referencia.json")
# Tablas cuyo contenido es catálogo fijo: deben tener exactamente las filas del SQL
CATALOGO = ["equipos", "componentes", "sensores", "rangos_operacion", "tipos_falla", "reglas_alarma", "roles"]

CONSULTAS = {
    "tablas": """
        SELECT c.relname, c.relkind::text, c.relrowsecurity::text
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %(e)s AND c.relkind IN ('r', 'p', 'v', 'm')""",
    "columnas": """
        SELECT c.relname || '.' || a.attname, format_type(a.atttypid, a.atttypmod),
               a.attnotnull::text, coalesce(pg_get_expr(d.adbin, d.adrelid), ''), a.attidentity::text
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE n.nspname = %(e)s AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped""",
    "restricciones": """
        SELECT c.relname || '.' || k.conname, k.contype::text, pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %(e)s""",
    "indices": """
        SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %(e)s""",
    "funciones": """
        SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')', md5(pg_get_functiondef(p.oid))
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %(e)s""",
    "triggers": """
        SELECT c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %(e)s AND NOT t.tgisinternal""",
    "extensiones": """
        SELECT e.extname, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'pgcrypto'""",
}

NOMBRES = {"tablas": "Tablas", "columnas": "Columnas", "restricciones": "Restricciones (PK/FK/UQ/CHECK)",
           "indices": "Índices", "funciones": "Funciones", "triggers": "Triggers", "extensiones": "Extensión pgcrypto",
           "catalogo": "Datos de catálogo"}


def leer_url(ruta: Path) -> str:
    if not ruta.exists():
        sys.exit(f"No existe {ruta}")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("DATABASE_URL="):
            return linea.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{ruta} no tiene DATABASE_URL")


def normalizar_check(defi: str) -> str:
    """Un mismo CHECK se escribe distinto según se creó con migraciones o desde el SQL completo
    (p. ej. ARRAY[('a'::varchar)::text] vs (ARRAY['a'::varchar])::text[]): se comparan sin conversiones ni paréntesis."""
    defi = re.sub(r"::(character varying|text|bpchar)(\[\])?", "", defi)
    return re.sub(r"[()\s]", "", defi)


def capturar(cur) -> dict:
    foto = {}
    for clave, sql in CONSULTAS.items():
        cur.execute(sql, {"e": ESQUEMA})
        foto[clave] = {fila[0]: list(fila[1:]) for fila in cur.fetchall()}
    for k, (tipo, defi) in foto["restricciones"].items():
        if tipo == "c":
            foto["restricciones"][k] = [tipo, normalizar_check(defi)]
    for k, (defi,) in foto["indices"].items():
        foto["indices"][k] = [normalizar_check(defi)]
    foto["catalogo"] = {}
    for t in CATALOGO:
        if t not in foto["tablas"]:
            continue  # la tabla no existe: ya se informa como faltante
        cur.execute(f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text COLLATE \"C\"), '')) FROM {ESQUEMA}.{t} x")
        n, huella = cur.fetchone()
        foto["catalogo"][t] = [str(n), huella]
    return foto


def comparar(ref: dict, real: dict) -> int:
    errores = 0
    print(f"\n{'Elemento':<34}{'Esperado':>9}{'En la base':>12}   Resultado")
    print("-" * 70)
    for clave in NOMBRES:
        r, b = ref.get(clave, {}), real.get(clave, {})
        faltan = sorted(set(r) - set(b))
        sobran = sorted(set(b) - set(r))
        distintos = sorted(k for k in set(r) & set(b) if r[k] != b[k])
        ok = not (faltan or sobran or distintos)
        print(f"{NOMBRES[clave]:<34}{len(r):>9}{len(b):>12}   {'OK' if ok else 'DIFERENCIAS'}")
        for k in faltan:
            print(f"     falta:     {k}")
        for k in sobran:
            print(f"     sobra:     {k}")
        for k in distintos:
            if clave == "catalogo":
                print(f"     distinto:  {k} (esperado {r[k][0]} filas, hay {b[k][0]}; o cambió su contenido)")
            else:
                print(f"     distinto:  {k}\n                esperado: {r[k]}\n                en base:  {b[k]}")
        errores += len(faltan) + len(sobran) + len(distintos)
    return errores


def main() -> None:
    ap = argparse.ArgumentParser(description="Valida el esquema mantpred contra la referencia v4.1 (solo lectura)")
    ap.add_argument("--env", default=str(Path.home() / "qla_rds_aws.env"), help="archivo con DATABASE_URL")
    ap.add_argument("--generar-referencia", action="store_true", help="guarda la estructura actual como referencia")
    args = ap.parse_args()
    url = leer_url(Path(args.env))
    print("Conectando a", url.split("@")[-1].split("?")[0], "...")
    with psycopg.connect(url, connect_timeout=20, autocommit=True) as con, con.cursor() as cur:
        cur.execute("SELECT version(), inet_server_addr()")
        version, ip = cur.fetchone()
        print("Servidor:", ip, "|", version.split(",")[0])
        foto = capturar(cur)

    if args.generar_referencia:
        REFERENCIA.write_text(json.dumps(foto, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print("Referencia guardada en", REFERENCIA)
        return

    if not REFERENCIA.exists():
        sys.exit(f"No se encontró {REFERENCIA.name} (debe estar junto a este script)")
    errores = comparar(json.loads(REFERENCIA.read_text(encoding="utf-8")), foto)
    total = sum(len(v) for v in foto.values())
    if errores:
        print(f"\nRESULTADO: el esquema de la base NO coincide con v4.1 ({errores} diferencias).")
        sys.exit(1)
    print(f"\nRESULTADO: el esquema de la base coincide con bd_mantpred_v4_1_completo.sql ({total} elementos revisados).")


if __name__ == "__main__":
    main()
