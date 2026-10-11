# Base de datos – Mantenimiento Predictivo QLA

Esquema PostgreSQL del sistema de mantenimiento predictivo del molino coloidal MC-01
(Química Latinoamericana S.A.). Alojado en Supabase, esquema `mantpred`.

Responsable: Nicolás (Ingeniería de datos y backend)
Versión: 2 — basada en el esquema original de Franco Carvajal
Creada en Supabase: 07-10-2026

## Contenido

| Archivo | Qué es |
| --- | --- |
| `bd_mantenimiento_predictivo_v2.sql` | Crea el esquema completo: 14 tablas, 2 vistas, 1 función, seguridad (RLS) y datos iniciales |
| `cargar_datos.py` | Carga una ventana del dataset simulado MC-01 en `lecturas` y `estados_equipo` (`fuente = 'simulado'`) |
| `.env.example` | Plantilla de la conexión a Supabase (copiar como `.env`, que no se sube al repositorio) |
| `requirements.txt` | Dependencias del script: `pandas` y `psycopg[binary]` |

## Qué crea el script

- **Acceso:** `roles` (administrador, supervisor, operador, visualizador), `usuarios` (clave bcrypt), `auditoria_accesos`
- **Planta y sensores:** `equipos` (MC-01), `sensores` (6 reales del SCADA + 41 simulados del dataset), `lecturas` (1 fila por sensor por minuto, columna `fuente` = real / simulado), `estados_equipo`, `tipos_emulsion`, `setpoints`, `lotes_produccion`
- **Fallas y mantenimiento:** `tipos_falla` (7 fallas del modelo + anomalía), `alarmas`, `predicciones`, `mantenimientos`
- **Vistas:** `v_ultima_lectura` (último valor por sensor, para el dashboard), `v_alarmas_activas`
- **Función:** `purgar_lecturas_simuladas(dias)` — borra lecturas simuladas antiguas (plan gratis = 500 MB)

## Cómo ejecutarlo

1. Supabase → SQL Editor → pegar todo el archivo → Run.
2. Verificar:
   ```sql
   SELECT count(*) FROM mantpred.sensores;     -- 47
   SELECT count(*) FROM mantpred.tipos_falla;  -- 8
   ```
3. Para recrear desde cero, descomentar `DROP SCHEMA IF EXISTS mantpred CASCADE;` al inicio.

## Cómo se conecta cada parte

- **Pipeline IoT / AWS:** inserta en `lecturas` (y `estados_equipo`).
- **Modelos:** leen `lecturas`, escriben en `predicciones` y `alarmas` (origen = 'modelo').
- **Backend / web:** lee todo; gestiona `usuarios`, `alarmas` reconocidas y `mantenimientos`.

El esquema no está expuesto por la API pública de Supabase (RLS activo, sin políticas):
solo se accede con conexión directa a PostgreSQL desde el backend.

## Importante

- Incluye 4 usuarios de prueba (`@demo.qla.cl`). **Se borran antes de la entrega final.**
- Nunca subir al repositorio la contraseña de la base ni la cadena de conexión de Supabase.

## Cargar datos simulados

```
pip install -r requirements.txt
python cargar_datos.py --csv RUTA/Dataset_Molino_QLA_Realista.zip --dry-run   # solo muestra qué cargaría
python cargar_datos.py --csv RUTA/Dataset_Molino_QLA_Realista.zip             # carga 14 días desde 2026-05-27
```

- Es seguro repetirlo: lo ya cargado se omite. Carga un día a la vez y se puede retomar si se corta.
- Otra ventana: `--inicio 2026-09-19 --dias 14`. Borrar lo simulado antes de cargar: `--reemplazar`.
- Tamaño medido: 826.560 lecturas (14 días) = 140 MB de los 500 MB del plan gratis (~170 bytes por lectura).
  Para liberar espacio: `SELECT mantpred.purgar_lecturas_simuladas(7);`
- La etiqueta de falla del dataset (`LABEL_Estado_Planta`) no se carga: en la planta real no existe.
- Las horas del dataset se interpretan como hora de Chile y se guardan en UTC.
