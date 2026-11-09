-- =====================================================================
-- MIGRACIÓN v4 — Normalización del esquema mantpred
-- Proyecto: Mantenimiento predictivo del molino coloidal MC-01 (QLA)
--
-- Se aplica sobre el esquema v3 (bd_mantenimiento_predictivo_v2.sql + migracion_v3.sql):
--     python ejecutar_sql.py migracion_v4.sql --env "%USERPROFILE%\qla_rds.env"
--
-- Cambios:
--   1. Nueva tabla COMPONENTES (TK-101, F-101, MC-01, ...). Reemplaza el texto libre "componente"
--      que se repetía en sensores, tipos_falla, reglas_alarma y mantenimientos.
--   2. Nueva tabla MANTENIMIENTO_FALLAS (N:M): qué modos de falla atiende cada intervención.
--      Una preventiva mensual atiende varios; una correctiva, uno. Reemplaza la búsqueda por
--      palabras en la descripción y la columna mantenimientos.tipo_falla_id.
--   3. Se eliminan las tablas sin uso del diseño inicial: setpoints, tipos_emulsion,
--      lotes_produccion (reemplazadas por reglas_alarma y rangos_operacion), las vistas y la
--      función de purga antigua que nadie usa, y las columnas sin uso o derivables:
--      alarmas.setpoint_id, alarmas.sensor_id (se obtiene de la regla), predicciones.vida_util_horas,
--      sensores.canal_plc, reglas_alarma.componente (se obtiene del sensor).
--   4. Restricciones CHECK por modelo en predicciones y por origen en alarmas.
--   5. Comentarios en todas las tablas (diccionario de datos dentro de la propia base).
--
-- No borra lecturas, estados, predicciones, alarmas, usuarios ni bitácora.
-- Todo ocurre en una transacción: si algo falla, no se aplica nada.
-- =====================================================================
BEGIN;
SET search_path TO mantpred, public;

-- ---------------------------------------------------------------------
-- 0. Objetos sin uso que dependen de columnas que cambian
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_alarmas_activas;
DROP VIEW IF EXISTS v_ultima_lectura;
DROP FUNCTION IF EXISTS purgar_lecturas_simuladas(integer);   -- reemplazada por purgar_datos_simulados

-- ---------------------------------------------------------------------
-- 1. COMPONENTES
-- ---------------------------------------------------------------------
CREATE TABLE componentes (
    id         SMALLINT     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id  INTEGER      NOT NULL REFERENCES equipos(id),
    codigo     VARCHAR(20)  NOT NULL UNIQUE,
    nombre     VARCHAR(80)  NOT NULL,
    tipo       VARCHAR(20)  NOT NULL
               CHECK (tipo IN ('estanque', 'instrumento', 'filtro', 'bomba', 'valvula', 'molino', 'intercambiador'))
);

INSERT INTO componentes (equipo_id, codigo, nombre, tipo)
SELECT e.id, c.codigo, c.nombre, c.tipo
FROM equipos e
CROSS JOIN (VALUES
    ('TK-101', 'Estanque de betún',                         'estanque'),
    ('TK-201', 'Estanque de solución jabonosa',               'estanque'),
    ('TK-301', 'Estanque de emulsión',                        'estanque'),
    ('TT-101', 'Sensor Pt100 de temperatura del betún',       'instrumento'),
    ('FT-101', 'Caudalímetro Coriolis de betún',              'instrumento'),
    ('FT-201', 'Caudalímetro Coriolis de solución',           'instrumento'),
    ('F-101',  'Filtro de línea',                             'filtro'),
    ('P-101',  'Bomba de la línea',                           'bomba'),
    ('V-101',  'Válvula de 3 vías y línea de aire',           'valvula'),
    ('MC-01',  'Molino coloidal',                             'molino'),
    ('E-301',  'Intercambiador de calor',                     'intercambiador')
) AS c (codigo, nombre, tipo)
WHERE e.codigo = 'MC-01';

-- ---------------------------------------------------------------------
-- 2. SENSORES: componente (texto) -> componente_id (FK)
--    Las 4 señales de la Pt100 del betún pasan a su instrumento, TT-101
--    (así coinciden con la regla PT100_SIN_ALIMENTACION y con la bitácora).
-- ---------------------------------------------------------------------
UPDATE sensores SET componente = 'TT-101'
WHERE tag IN ('TEM_son_betum_in', 'RES_son_betum_in', 'VOLT_son_betum_in', 'AMP_son_betum_in');

ALTER TABLE sensores ADD COLUMN componente_id SMALLINT REFERENCES componentes(id);
UPDATE sensores s SET componente_id = c.id FROM componentes c WHERE c.codigo = s.componente;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM sensores WHERE componente_id IS NULL) THEN
        RAISE EXCEPTION 'Hay sensores sin componente: %',
            (SELECT string_agg(tag || ' (' || coalesce(componente, 'sin componente') || ')', ', ')
             FROM sensores WHERE componente_id IS NULL);
    END IF;
END $$;
ALTER TABLE sensores ALTER COLUMN componente_id SET NOT NULL;
ALTER TABLE sensores DROP COLUMN componente;
ALTER TABLE sensores DROP COLUMN canal_plc;
CREATE INDEX ix_sensores_componente ON sensores (componente_id);

-- ---------------------------------------------------------------------
-- 3. TIPOS_FALLA: componente (texto) -> componente_id (FK)
--    La anomalía desconocida no tiene un componente asignado (NULL).
-- ---------------------------------------------------------------------
ALTER TABLE tipos_falla ADD COLUMN componente_id SMALLINT REFERENCES componentes(id);
UPDATE tipos_falla t SET componente_id = c.id FROM componentes c
WHERE c.codigo = t.componente AND t.codigo <> 'Anomalia_Desconocida';
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM tipos_falla WHERE componente_id IS NULL AND codigo <> 'Anomalia_Desconocida') THEN
        RAISE EXCEPTION 'Hay tipos de falla sin componente';
    END IF;
END $$;
ALTER TABLE tipos_falla DROP COLUMN componente;

-- ---------------------------------------------------------------------
-- 4. REGLAS_ALARMA: el componente se obtiene del sensor (3FN)
-- ---------------------------------------------------------------------
ALTER TABLE reglas_alarma DROP COLUMN componente;

-- ---------------------------------------------------------------------
-- 5. MANTENIMIENTOS: componente (texto) -> componente_id (FK, NULL = toda la línea)
--    + MANTENIMIENTO_FALLAS: modos de falla que atiende cada intervención
-- ---------------------------------------------------------------------
ALTER TABLE mantenimientos ADD COLUMN componente_id SMALLINT REFERENCES componentes(id);
UPDATE mantenimientos m SET componente_id = c.id FROM componentes c
WHERE c.codigo = split_part(m.componente, ' ', 1);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM mantenimientos WHERE componente_id IS NULL AND componente <> 'Planta completa') THEN
        RAISE EXCEPTION 'Hay mantenimientos con un componente desconocido: %',
            (SELECT string_agg(DISTINCT componente, ', ') FROM mantenimientos
             WHERE componente_id IS NULL AND componente <> 'Planta completa');
    END IF;
END $$;

CREATE TABLE mantenimiento_fallas (
    mantenimiento_id  INTEGER   NOT NULL REFERENCES mantenimientos(id) ON DELETE CASCADE,
    tipo_falla_id     SMALLINT  NOT NULL REFERENCES tipos_falla(id),
    PRIMARY KEY (mantenimiento_id, tipo_falla_id)
);
CREATE INDEX ix_mant_fallas_falla ON mantenimiento_fallas (tipo_falla_id);

-- Correctivas: la falla que repararon
INSERT INTO mantenimiento_fallas (mantenimiento_id, tipo_falla_id)
SELECT id, tipo_falla_id FROM mantenimientos WHERE tipo_falla_id IS NOT NULL;

-- Preventivas: cada tarea de la descripción atiende un modo de falla
-- (mismas frases que usa el modelo predictivo para reiniciar el desgaste de cada equipo)
INSERT INTO mantenimiento_fallas (mantenimiento_id, tipo_falla_id)
SELECT m.id, tf.id
FROM mantenimientos m
JOIN (VALUES
    ('limpieza de filtro',               'Filtro_Obstruido'),
    ('antena del radar',                 'Advertencia_Radar_Sucio_Betun'),
    ('mantención de caldera',            'Sobrecarga_Motor_Por_Asfalto_Frio'),
    ('intercambiador',                   'Ensuciamiento_Intercambiador'),
    ('transmisor de caudal',             'Cortocircuito_Transmisor_Caudal_Sol'),
    ('borneras',                         'Falla_Electrica_PT100_Betun'),
    ('cambio preventivo de rodamientos', 'Desgaste_Rodamientos_Molino')
) AS k (frase, falla) ON m.tipo = 'preventivo' AND lower(m.descripcion) LIKE '%' || k.frase || '%'
JOIN tipos_falla tf ON tf.codigo = k.falla
ON CONFLICT DO NOTHING;

ALTER TABLE mantenimientos DROP COLUMN componente;
ALTER TABLE mantenimientos DROP COLUMN tipo_falla_id;
CREATE INDEX ix_mantenimientos_componente ON mantenimientos (componente_id);

-- ---------------------------------------------------------------------
-- 6. ALARMAS: sin setpoints; el sensor se obtiene de la regla
-- ---------------------------------------------------------------------
ALTER TABLE alarmas DROP CONSTRAINT IF EXISTS alarmas_check2;          -- origen setpoint -> sensor
ALTER TABLE alarmas DROP CONSTRAINT IF EXISTS alarmas_origen_check;
ALTER TABLE alarmas DROP COLUMN setpoint_id;
ALTER TABLE alarmas DROP COLUMN sensor_id;
UPDATE alarmas SET clave = origen || ':' || id WHERE clave IS NULL;
ALTER TABLE alarmas ALTER COLUMN clave SET NOT NULL;
ALTER TABLE alarmas ADD CONSTRAINT alarmas_origen_check CHECK (origen IN ('regla', 'modelo'));
ALTER TABLE alarmas ADD CONSTRAINT alarmas_regla_check
    CHECK (origen <> 'regla' OR (regla_id IS NOT NULL AND tipo_falla_id IS NULL));

DROP TABLE setpoints;
DROP TABLE lotes_produccion;
DROP TABLE tipos_emulsion;

-- ---------------------------------------------------------------------
-- 7. PREDICCIONES: sin vida útil (ningún modelo la calcula) y reglas por modelo
-- ---------------------------------------------------------------------
ALTER TABLE predicciones DROP COLUMN vida_util_horas;
ALTER TABLE predicciones ADD CONSTRAINT predicciones_horizonte_modelo_check
    CHECK ((modelo = 'predictivo') = (horizonte <> 'actual'));
ALTER TABLE predicciones ADD CONSTRAINT predicciones_predictivo_check
    CHECK (modelo <> 'predictivo' OR tipo_falla_id IS NOT NULL);
ALTER TABLE predicciones ADD CONSTRAINT predicciones_autoencoder_check
    CHECK (modelo <> 'autoencoder' OR (tipo_falla_id IS NULL AND prob_falla IS NULL));
ALTER TABLE predicciones ADD CONSTRAINT predicciones_diagnostico_check
    CHECK (modelo <> 'diagnostico' OR error_ae IS NULL);

-- ---------------------------------------------------------------------
-- 8. Seguridad: la tabla nueva queda igual que las demás (sin acceso por la API de datos)
-- ---------------------------------------------------------------------
ALTER TABLE componentes ENABLE ROW LEVEL SECURITY;
ALTER TABLE mantenimiento_fallas ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- 9. Diccionario de datos dentro de la base
-- ---------------------------------------------------------------------
COMMENT ON SCHEMA mantpred IS 'Mantenimiento predictivo del molino coloidal MC-01 de Química Latinoamericana';
COMMENT ON TABLE equipos IS 'Equipos monitoreados. Hoy, el molino coloidal MC-01';
COMMENT ON TABLE componentes IS 'Partes de la línea del equipo (estanques, instrumentos, filtro, bomba, válvula, molino, intercambiador), identificadas por su tag de planta';
COMMENT ON TABLE sensores IS 'Catálogo de señales medidas: 41 del dataset simulado y 6 tags reales del PLC. normal_min/normal_max = banda general cuando no hay banda por modo en rangos_operacion';
COMMENT ON TABLE lecturas IS 'Valor de cada sensor por minuto. Una fila por sensor, fuente y minuto';
COMMENT ON TABLE estados_equipo IS 'Modo de operación del equipo por minuto (producción, limpieza, espera, preparación, detenida) y tipo de asfalto';
COMMENT ON TABLE rangos_operacion IS 'Banda normal de cada sensor según modo de operación y tipo de asfalto (percentiles 2,5 y 97,5 de la operación sana)';
COMMENT ON TABLE tipos_falla IS 'Modos de falla que reconocen los modelos: 7 fallas y la anomalía desconocida';
COMMENT ON TABLE predicciones IS 'Resultados de los 3 modelos. diagnostico y autoencoder: uno por minuto (horizonte actual). predictivo: uno por hora, falla y horizonte (24h, 5d, 15d)';
COMMENT ON TABLE reglas_alarma IS 'Reglas fijas sobre un sensor: límites de instrumento y de proceso';
COMMENT ON TABLE condiciones_minuto IS 'Condiciones de alarma que se cumplieron cada minuto (modelo o regla). Base de la regla 3 de 5';
COMMENT ON TABLE alarmas IS 'Alarmas abiertas y cerradas. Origen modelo (tipo_falla_id) o regla (regla_id). Una sola activa por clave';
COMMENT ON TABLE mantenimientos IS 'Bitácora de intervenciones de la planta. componente_id NULL = intervención de toda la línea (preventiva mensual)';
COMMENT ON TABLE mantenimiento_fallas IS 'Modos de falla que atiende cada intervención: una correctiva atiende uno; una preventiva, varios';
COMMENT ON TABLE roles IS 'Roles del sistema: operador (nivel 2) y administrador (nivel 4)';
COMMENT ON TABLE usuarios IS 'Usuarios del dashboard. Clave con bcrypt, bloqueo por intentos fallidos';
COMMENT ON TABLE auditoria_accesos IS 'Registro de ingresos y acciones administrativas';
COMMENT ON COLUMN lecturas.fuente IS 'simulado (dataset) o real (planta)';
COMMENT ON COLUMN predicciones.metodo IS 'LightGBM o Tendencia (predictivo); Autoencoder (vigilancia)';
COMMENT ON COLUMN predicciones.error_ae IS 'Error de reconstrucción (MSE) del autoencoder';
COMMENT ON COLUMN predicciones.dias_estimados IS 'Días hasta cruzar el límite físico, en las fallas raras (método Tendencia)';
COMMENT ON COLUMN alarmas.clave IS 'Condición que la originó: modelo:<falla> o regla:<código>';
COMMENT ON COLUMN alarmas.detalle IS 'Origen en palabras y sensores señalados por el autoencoder';

COMMIT;
