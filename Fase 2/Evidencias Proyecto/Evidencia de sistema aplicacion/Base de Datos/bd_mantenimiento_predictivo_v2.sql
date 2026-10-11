-- =====================================================================
-- Proyecto : Mantenimiento predictivo inteligente
-- Cliente  : Química Latinoamericana S.A.
-- Motor    : PostgreSQL 15+ (probado para Supabase)
-- Versión  : 2 (basada en el esquema de Franco Carvajal)
--
-- Cambios respecto a la versión 1
--  * Roles: se agregan 'operador' y 'visualizador' (4 niveles de acceso).
--  * Usuarios: debe_cambiar_clave e intentos fallidos para el login.
--  * Sensores: componente (TK-101, MC-01...), rango normal y origen
--    ('real' = existe en la planta hoy, 'simulado' = solo en el simulador).
--  * Lecturas: columna fuente ('real' / 'simulado'). Permite tener datos
--    reales y simulados juntos y cambiar de uno a otro sin tocar código.
--  * Estados de equipo: mismos estados que el dataset (Produccion, Limpieza...).
--  * Catálogo tipos_falla: las 7 fallas del modelo + anomalía desconocida.
--  * Alarmas: ahora pueden venir de un setpoint, de una regla fija o de un
--    modelo; guardan inicio y fin del episodio (no una fila por minuto).
--  * Predicciones: modelo, horizonte (actual, 24h, 5d, 15d) y falla.
--  * Mantenimientos: enlazados a la falla y a la alarma que los originó.
--  * RLS activado en todas las tablas (la API entra como postgres).
--
-- Cómo ejecutarlo en Supabase: SQL Editor -> pegar todo -> Run.
-- Para volver a crearlo desde cero, descomenta la línea DROP de abajo.
-- =====================================================================

-- DROP SCHEMA IF EXISTS mantpred CASCADE;

BEGIN;

-- En Supabase pgcrypto vive en el esquema "extensions"
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

CREATE SCHEMA IF NOT EXISTS mantpred;
SET search_path TO mantpred, extensions;

-- =====================================================================
-- 1. USUARIOS Y ACCESO
-- =====================================================================

CREATE TABLE roles (
    id           SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre       VARCHAR(30)  NOT NULL UNIQUE
                 CHECK (nombre IN ('administrador', 'supervisor', 'operador', 'visualizador')),
    nivel        SMALLINT     NOT NULL UNIQUE CHECK (nivel BETWEEN 1 AND 4),  -- 4 = máximo
    descripcion  VARCHAR(200)
);

CREATE TABLE usuarios (
    id                 INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rol_id             SMALLINT     NOT NULL REFERENCES roles (id),
    nombre             VARCHAR(120) NOT NULL,
    email              VARCHAR(150) NOT NULL,
    password_hash      VARCHAR(255) NOT NULL,      -- bcrypt, nunca texto plano
    activo             BOOLEAN      NOT NULL DEFAULT TRUE,
    debe_cambiar_clave BOOLEAN      NOT NULL DEFAULT TRUE,
    intentos_fallidos  SMALLINT     NOT NULL DEFAULT 0,
    bloqueado_hasta    TIMESTAMPTZ,
    ultimo_acceso      TIMESTAMPTZ,
    creado_en          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_usuarios_email ON usuarios (lower(email));
CREATE INDEX ix_usuarios_rol ON usuarios (rol_id);

CREATE TABLE auditoria_accesos (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id  INTEGER     REFERENCES usuarios (id) ON DELETE SET NULL,
    email       VARCHAR(150),                      -- se guarda aunque el usuario no exista
    fecha       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip          INET,
    accion      VARCHAR(50) NOT NULL,              -- login_ok, login_fallido, logout, cambio_clave, usuario_creado...
    detalle     VARCHAR(250)
);
CREATE INDEX ix_auditoria_usuario_fecha ON auditoria_accesos (usuario_id, fecha DESC);

-- =====================================================================
-- 2. PLANTA Y SENSORES
-- =====================================================================

CREATE TABLE equipos (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo     VARCHAR(20)  NOT NULL UNIQUE,       -- MC-01
    nombre     VARCHAR(100) NOT NULL UNIQUE,
    tipo       VARCHAR(60)  NOT NULL,
    marca      VARCHAR(60),
    modelo     VARCHAR(60),
    potencia   VARCHAR(40),
    ubicacion  VARCHAR(120)
);

CREATE TABLE sensores (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id    INTEGER      NOT NULL REFERENCES equipos (id),
    tag          VARCHAR(40)  NOT NULL UNIQUE,     -- igual que en SCADA o en el dataset
    nombre       VARCHAR(80)  NOT NULL,            -- texto para mostrar en pantalla
    componente   VARCHAR(20),                      -- TK-101, FT-101, F-101, MC-01, E-301...
    variable     VARCHAR(40)  NOT NULL,            -- caudal, temperatura, presion, vibracion, corriente...
    tipo_sensor  VARCHAR(80)  NOT NULL,
    unidad       VARCHAR(15)  NOT NULL,
    rango_min    NUMERIC(12,3),                    -- rango del instrumento
    rango_max    NUMERIC(12,3),
    normal_min   NUMERIC(12,3),                    -- operación normal (para calidad de datos y gráficos)
    normal_max   NUMERIC(12,3),
    senal        VARCHAR(20)  NOT NULL DEFAULT '4-20 mA',
    canal_plc    VARCHAR(30),
    origen       VARCHAR(10)  NOT NULL DEFAULT 'real'
                 CHECK (origen IN ('real', 'simulado')),
    activo       BOOLEAN      NOT NULL DEFAULT TRUE,
    descripcion  VARCHAR(250),
    CHECK (rango_min  IS NULL OR rango_max  IS NULL OR rango_min  < rango_max),
    CHECK (normal_min IS NULL OR normal_max IS NULL OR normal_min <= normal_max)
);
CREATE INDEX ix_sensores_equipo ON sensores (equipo_id);

-- Serie temporal: un valor por sensor, instante y fuente (cada 1 minuto)
CREATE TABLE lecturas (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id  INTEGER       NOT NULL REFERENCES sensores (id),
    ts         TIMESTAMPTZ   NOT NULL,
    valor      NUMERIC(12,3),                      -- NULL si no llegó dato
    calidad    VARCHAR(10)   NOT NULL DEFAULT 'buena'
               CHECK (calidad IN ('buena', 'dudosa', 'mala')),
    fuente     VARCHAR(10)   NOT NULL DEFAULT 'real'
               CHECK (fuente IN ('real', 'simulado')),
    UNIQUE (sensor_id, fuente, ts)                 -- evita duplicados y sirve de índice para tendencias
);
CREATE INDEX ix_lecturas_ts ON lecturas (ts);

-- Modo de operación de la planta en cada minuto (contexto para los modelos)
CREATE TABLE estados_equipo (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id    INTEGER     NOT NULL REFERENCES equipos (id),
    ts           TIMESTAMPTZ NOT NULL,
    estado       VARCHAR(15) NOT NULL
                 CHECK (estado IN ('detenida', 'preparacion', 'produccion', 'espera',
                                   'limpieza', 'mantenimiento', 'falla')),
    tipo_asfalto VARCHAR(15)
                 CHECK (tipo_asfalto IN ('convencional', 'plastomerico', 'ninguno')),
    fuente       VARCHAR(10) NOT NULL DEFAULT 'real'
                 CHECK (fuente IN ('real', 'simulado')),
    UNIQUE (equipo_id, fuente, ts)
);

CREATE TABLE tipos_emulsion (
    id           SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo       VARCHAR(20)  NOT NULL UNIQUE,
    descripcion  VARCHAR(200)
);

CREATE TABLE setpoints (
    id                INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id         INTEGER       NOT NULL REFERENCES sensores (id),
    tipo_emulsion_id  SMALLINT      NOT NULL REFERENCES tipos_emulsion (id),
    valor_sp          NUMERIC(10,3) NOT NULL,
    alarma_min        NUMERIC(10,3),
    alarma_max        NUMERIC(10,3),
    seguridad_min     NUMERIC(10,3),
    seguridad_max     NUMERIC(10,3),
    definido_por      INTEGER       NOT NULL REFERENCES usuarios (id),
    vigente_desde     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (alarma_min IS NULL OR seguridad_min IS NULL OR seguridad_min <= alarma_min),
    CHECK (alarma_max IS NULL OR seguridad_max IS NULL OR seguridad_max >= alarma_max),
    CHECK (alarma_min IS NULL OR alarma_max    IS NULL OR alarma_min    <  alarma_max),
    UNIQUE (sensor_id, tipo_emulsion_id, vigente_desde)
);

CREATE TABLE lotes_produccion (
    id                INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id         INTEGER     NOT NULL REFERENCES equipos (id),
    tipo_emulsion_id  SMALLINT    NOT NULL REFERENCES tipos_emulsion (id),
    supervisor_id     INTEGER     NOT NULL REFERENCES usuarios (id),
    inicio            TIMESTAMPTZ NOT NULL,
    fin               TIMESTAMPTZ,
    toneladas         NUMERIC(8,2),
    CHECK (fin IS NULL OR fin > inicio)
);
CREATE INDEX ix_lotes_equipo_inicio ON lotes_produccion (equipo_id, inicio DESC);

-- =====================================================================
-- 3. FALLAS, ALARMAS, PREDICCIONES Y MANTENIMIENTO
-- =====================================================================

CREATE TABLE tipos_falla (
    id          SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo      VARCHAR(60)  NOT NULL UNIQUE,      -- mismo texto que la etiqueta del modelo
    titulo      VARCHAR(100) NOT NULL,
    componente  VARCHAR(20),
    prioridad   VARCHAR(10)  NOT NULL CHECK (prioridad IN ('baja', 'media', 'alta')),
    accion      VARCHAR(250)                       -- qué debe hacer el operador
);

CREATE TABLE alarmas (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id       INTEGER      NOT NULL REFERENCES equipos (id),
    origen          VARCHAR(10)  NOT NULL
                    CHECK (origen IN ('setpoint', 'regla', 'modelo')),
    sensor_id       INTEGER      REFERENCES sensores (id),     -- obligatorio si viene de un setpoint
    setpoint_id     INTEGER      REFERENCES setpoints (id),
    tipo_falla_id   SMALLINT     REFERENCES tipos_falla (id),  -- obligatorio si viene del modelo
    inicio          TIMESTAMPTZ  NOT NULL,
    fin             TIMESTAMPTZ,                               -- NULL mientras siga activa
    valor           NUMERIC(12,3),
    severidad       VARCHAR(12)  NOT NULL
                    CHECK (severidad IN ('aviso', 'advertencia', 'critica')),
    mensaje         VARCHAR(250),
    fuente          VARCHAR(10)  NOT NULL DEFAULT 'real'
                    CHECK (fuente IN ('real', 'simulado')),
    reconocida_por  INTEGER      REFERENCES usuarios (id),
    reconocida_en   TIMESTAMPTZ,
    comentario      VARCHAR(250),                              -- retroalimentación del operador
    CHECK ((reconocida_por IS NULL) = (reconocida_en IS NULL)),
    CHECK (fin IS NULL OR fin >= inicio),
    CHECK (origen <> 'setpoint' OR sensor_id IS NOT NULL),
    CHECK (origen <> 'modelo'   OR tipo_falla_id IS NOT NULL)
);
CREATE INDEX ix_alarmas_equipo_inicio ON alarmas (equipo_id, inicio DESC);
CREATE INDEX ix_alarmas_activas ON alarmas (equipo_id) WHERE fin IS NULL;
CREATE INDEX ix_alarmas_pendientes ON alarmas (inicio DESC) WHERE reconocida_en IS NULL;

CREATE TABLE predicciones (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id        INTEGER      NOT NULL REFERENCES equipos (id),
    ts               TIMESTAMPTZ  NOT NULL,
    modelo           VARCHAR(15)  NOT NULL
                     CHECK (modelo IN ('diagnostico', 'autoencoder', 'predictivo')),
    modelo_version   VARCHAR(30)  NOT NULL,
    horizonte        VARCHAR(6)   NOT NULL DEFAULT 'actual'
                     CHECK (horizonte IN ('actual', '24h', '5d', '15d')),
    tipo_falla_id    SMALLINT     REFERENCES tipos_falla (id), -- NULL = normal
    prob_falla       NUMERIC(5,4) CHECK (prob_falla BETWEEN 0 AND 1),
    indice_salud     NUMERIC(6,2),                             -- autoencoder (0-100)
    vida_util_horas  NUMERIC(10,1) CHECK (vida_util_horas >= 0),
    fuente           VARCHAR(10)  NOT NULL DEFAULT 'real'
                     CHECK (fuente IN ('real', 'simulado')),
    UNIQUE NULLS NOT DISTINCT (equipo_id, modelo, horizonte, tipo_falla_id, ts)
);
CREATE INDEX ix_pred_equipo_ts ON predicciones (equipo_id, ts DESC);

CREATE TABLE mantenimientos (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id       INTEGER      NOT NULL REFERENCES equipos (id),
    registrado_por  INTEGER      NOT NULL REFERENCES usuarios (id),
    componente      VARCHAR(60)  NOT NULL,         -- F-101 filtro, MC-01 rodamientos...
    tipo            VARCHAR(12)  NOT NULL
                    CHECK (tipo IN ('preventivo', 'correctivo', 'predictivo')),
    tipo_falla_id   SMALLINT     REFERENCES tipos_falla (id),  -- etiqueta para reentrenar el modelo
    alarma_id       BIGINT       REFERENCES alarmas (id),      -- alarma que lo originó, si hubo
    fecha_inicio    TIMESTAMPTZ  NOT NULL,
    fecha_fin       TIMESTAMPTZ,
    descripcion     TEXT,
    CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio)
);
CREATE INDEX ix_mant_equipo_fecha ON mantenimientos (equipo_id, fecha_inicio DESC);

-- =====================================================================
-- 4. VISTAS PARA EL DASHBOARD
-- =====================================================================

-- Última lectura de cada sensor activo, por fuente
CREATE VIEW v_ultima_lectura AS
SELECT DISTINCT ON (s.id, l.fuente)
       s.id AS sensor_id, s.tag, s.nombre, s.componente, s.variable, s.unidad,
       s.normal_min, s.normal_max, l.fuente, l.ts, l.valor, l.calidad,
       (l.valor < s.normal_min OR l.valor > s.normal_max) AS fuera_de_rango
FROM sensores s
JOIN lecturas l ON l.sensor_id = s.id
WHERE s.activo
ORDER BY s.id, l.fuente, l.ts DESC;

-- Alarmas activas con su texto listo para mostrar
CREATE VIEW v_alarmas_activas AS
SELECT a.id, e.codigo AS equipo, a.origen, a.severidad, a.inicio, a.valor, a.fuente,
       COALESCE(a.mensaje, tf.titulo) AS mensaje, tf.accion,
       s.tag AS sensor, a.reconocida_en IS NOT NULL AS reconocida
FROM alarmas a
JOIN equipos e ON e.id = a.equipo_id
LEFT JOIN tipos_falla tf ON tf.id = a.tipo_falla_id
LEFT JOIN sensores s ON s.id = a.sensor_id
WHERE a.fin IS NULL;

-- =====================================================================
-- 5. MANTENCIÓN DE LA BASE
--    Borra lecturas simuladas antiguas para no llenar el plan gratis.
--    Uso: SELECT mantpred.purgar_lecturas_simuladas(30);
-- =====================================================================

CREATE FUNCTION purgar_lecturas_simuladas(dias INTEGER)
RETURNS BIGINT LANGUAGE sql AS $$
    WITH borradas AS (
        DELETE FROM mantpred.lecturas
        WHERE fuente = 'simulado'
          AND ts < (SELECT max(ts) FROM mantpred.lecturas WHERE fuente = 'simulado')
                   - make_interval(days => dias)
        RETURNING 1)
    SELECT count(*) FROM borradas;
$$;

-- =====================================================================
-- 6. SEGURIDAD: RLS en todas las tablas.
--    Sin políticas, nadie entra por la API pública de Supabase; el
--    backend se conecta como postgres y no se ve afectado.
-- =====================================================================

DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'mantpred' LOOP
        EXECUTE format('ALTER TABLE mantpred.%I ENABLE ROW LEVEL SECURITY', t);
    END LOOP;
END $$;

-- =====================================================================
-- 7. DATOS INICIALES
-- =====================================================================

INSERT INTO roles (nombre, nivel, descripcion) VALUES
 ('administrador', 4, 'Gestiona usuarios, equipos, sensores y configuración general'),
 ('supervisor',    3, 'Define setpoints, gestiona lotes, registra mantenimientos y reconoce alarmas'),
 ('operador',      2, 'Monitorea el dashboard y reconoce alarmas con comentario'),
 ('visualizador',  1, 'Solo consulta el dashboard y los reportes');

INSERT INTO tipos_emulsion (codigo, descripcion) VALUES
 ('CRS-2',        'Emulsión catiónica de quiebre rápido'),
 ('CONVENCIONAL', 'Asfalto convencional (dataset simulado)'),
 ('PLASTOMERICO', 'Asfalto plastomérico (dataset simulado)');

INSERT INTO equipos (codigo, nombre, tipo, potencia, ubicacion) VALUES
 ('MC-01', 'Molino coloidal HP 240', 'Molino coloidal de emulsión',
  '100 hp, 2.900 RPM', 'Planta de emulsiones, El Salto');

INSERT INTO tipos_falla (codigo, titulo, componente, prioridad, accion) VALUES
 ('Sobrecarga_Motor_Por_Asfalto_Frio',   'Sobrecarga del motor por asfalto frío', 'TK-101', 'alta',
  'Revisar caldera y calefacción de TK-101 antes de seguir cargando el molino.'),
 ('Filtro_Obstruido',                    'Filtro obstruido', 'F-101', 'alta',
  'Limpiar el filtro F-101: la presión diferencial supera el límite y cae el caudal.'),
 ('Advertencia_Radar_Sucio_Betun',       'Radar del estanque de betún sucio', 'TK-101', 'media',
  'Programar limpieza de la antena del radar de TK-101.'),
 ('Cortocircuito_Transmisor_Caudal_Sol', 'Cortocircuito en transmisor de caudal de solución', 'FT-201', 'alta',
  'Revisar el lazo 4-20 mA de FT-201: la señal está saturada.'),
 ('Falla_Electrica_PT100_Betun',         'Falla eléctrica en Pt100 del betún', 'TT-101', 'alta',
  'Revisar alimentación de 24 V y borneras de la Pt100 de TK-101.'),
 ('Ensuciamiento_Intercambiador',        'Intercambiador sucio', 'E-301', 'media',
  'Programar limpieza química del intercambiador E-301.'),
 ('Desgaste_Rodamientos_Molino',         'Desgaste de rodamientos del molino', 'MC-01', 'alta',
  'Programar cambio de rodamientos del molino MC-01.'),
 ('Anomalia_Desconocida',                'Comportamiento anómalo no clasificado', 'MC-01', 'media',
  'El molino se aleja de su comportamiento sano. Revisar los sensores señalados.');

-- 7a. Sensores REALES: registro SCADA actual (hoja Data60, 1 lectura por minuto)
--     Rangos normales de temperatura según lo observado; los de caudal y presión
--     quedan pendientes de confirmar con QLA.
INSERT INTO sensores (equipo_id, tag, nombre, componente, variable, tipo_sensor, unidad,
                      normal_min, normal_max, origen, descripcion) VALUES
 (1, 'ASFALTO',    'Caudal de asfalto',      'FT-101', 'caudal',      'Caudalímetro Siemens',  'L/min', NULL, NULL, 'real', 'Observado ~299 L/min en producción'),
 (1, 'SOLUCION',   'Caudal de solución',     'FT-201', 'caudal',      'Caudalímetro Siemens',  'L/min', NULL, NULL, 'real', 'Observado ~225 L/min en producción'),
 (1, 'T_ASFALTO',  'Temperatura de asfalto', 'TK-101', 'temperatura', 'Termocupla tipo J',     '°C',    130,  145,  'real', NULL),
 (1, 'T_EMULSION', 'Temperatura de emulsión','TK-301', 'temperatura', 'Termocupla tipo J',     '°C',    70,   80,   'real', NULL),
 (1, 'T_SOLUCION', 'Temperatura de solución','TK-201', 'temperatura', 'Termocupla tipo J',     '°C',    30,   40,   'real', NULL),
 (1, 'RT_PRESION', 'Presión de línea',       'E-301',  'presion',     'Transmisor de presión', 'bar',   NULL, NULL, 'real', 'Ubicación exacta por confirmar con QLA');

-- 7b. Sensores SIMULADOS: columnas del Dataset_Molino_QLA_Realista (diccionario MC-01)
INSERT INTO sensores (equipo_id, tag, nombre, componente, variable, tipo_sensor, unidad,
                      rango_min, rango_max, normal_min, normal_max, senal, origen) VALUES
 (1,'TEM_son_betum_in',       'Temperatura betún',            'TK-101','temperatura','Pt100 TT-101',      '°C',   0,  250, 130, 200,  '4-20 mA','simulado'),
 (1,'RES_son_betum_in',       'Resistencia Pt100 betún',      'TK-101','resistencia','Pt100 TT-101',      'Ω',    NULL,NULL,150,178, 'directa','simulado'),
 (1,'VOLT_son_betum_in',      'Alimentación Pt100 betún',     'TK-101','voltaje',    'Transmisor TT-101', 'V',    NULL,NULL,23, 25,  'directa','simulado'),
 (1,'AMP_son_betum_in',       'Lazo Pt100 betún',             'TK-101','corriente_lazo','Transmisor TT-101','mA', 4,  20,  NULL,NULL,'4-20 mA','simulado'),
 (1,'AMP_cau_betum_in',       'Lazo caudal betún',            'FT-101','corriente_lazo','Coriolis FT-101', 'mA',  4,  20,  NULL,NULL,'4-20 mA','simulado'),
 (1,'FRE_cau_betum_in',       'Frecuencia Coriolis betún',    'FT-101','frecuencia', 'Coriolis FT-101',   'Hz',   NULL,NULL,NULL,NULL,'directa','simulado'),
 (1,'VOLT_cau_betum_in',      'Alimentación Coriolis betún',  'FT-101','voltaje',    'Coriolis FT-101',   'V',    NULL,NULL,23, 25,  'directa','simulado'),
 (1,'AMP_niv_betum_dep',      'Lazo radar betún',             'TK-101','corriente_lazo','Radar TK-101',   'mA',   4,  20,  NULL,NULL,'4-20 mA','simulado'),
 (1,'VOLT_niv_betum_dep',     'Alimentación radar betún',     'TK-101','voltaje',    'Radar TK-101',      'V',    NULL,NULL,23, 25,  'directa','simulado'),
 (1,'DIS_niv_betum_dep',      'Distancia radar betún',        'TK-101','distancia',  'Radar TK-101',      'm',    0,  15,  NULL,NULL,'directa','simulado'),
 (1,'POR_niv_betum_dep',      'Nivel estanque betún',         'TK-101','nivel',      'Radar TK-101',      '%',    0,  100, 5,  95,  'directa','simulado'),
 (1,'VOL_niv_betum_dep',      'Volumen estanque betún',       'TK-101','volumen',    'Radar TK-101',      'L',    0,  30000,NULL,NULL,'directa','simulado'),
 (1,'AMP_eco_betum_dep',      'Eco radar betún',              'TK-101','eco',        'Radar TK-101',      'dB',   NULL,NULL,25, 80,  'directa','simulado'),
 (1,'EST_niv_betum_dep',      'Estado NAMUR radar betún',     'TK-101','estado',     'Radar TK-101',      '0/1',  NULL,NULL,0,  0,   'digital','simulado'),
 (1,'TEM_son_solucion_in',    'Temperatura solución',         'TK-201','temperatura','Pt100 TT-201',      '°C',   0,  100, 20, 50,  '4-20 mA','simulado'),
 (1,'RES_son_solucion_in',    'Resistencia Pt100 solución',   'TK-201','resistencia','Pt100 TT-201',      'Ω',    NULL,NULL,107,120, 'directa','simulado'),
 (1,'AMP_son_solucion_in',    'Lazo Pt100 solución',          'TK-201','corriente_lazo','Transmisor TT-201','mA', 4,  20,  NULL,NULL,'4-20 mA','simulado'),
 (1,'AMP_cau_solucion_in',    'Lazo caudal solución',         'FT-201','corriente_lazo','Coriolis FT-201', 'mA',  4,  20,  3.8,20.5,'4-20 mA','simulado'),
 (1,'FRE_cau_solucion_in',    'Frecuencia Coriolis solución', 'FT-201','frecuencia', 'Coriolis FT-201',   'Hz',   NULL,NULL,NULL,NULL,'directa','simulado'),
 (1,'DIS_niv_solucion_dep',   'Distancia radar solución',     'TK-201','distancia',  'Radar TK-201',      'm',    0,  15,  NULL,NULL,'directa','simulado'),
 (1,'POR_niv_solucion_dep',   'Nivel estanque solución',      'TK-201','nivel',      'Radar TK-201',      '%',    0,  100, 5,  90,  'directa','simulado'),
 (1,'AMP_eco_solucion_dep',   'Eco radar solución',           'TK-201','eco',        'Radar TK-201',      'dB',   NULL,NULL,25, 85,  'directa','simulado'),
 (1,'TEM_son_emulsion_out',   'Temperatura emulsión',         'TK-301','temperatura','Pt100 TT-301',      '°C',   0,  100, 35, 85,  '4-20 mA','simulado'),
 (1,'RES_son_emulsion_out',   'Resistencia Pt100 emulsión',   'TK-301','resistencia','Pt100 TT-301',      'Ω',    NULL,NULL,113,133, 'directa','simulado'),
 (1,'AMP_cau_emulsion_out',   'Lazo caudal emulsión',         'TK-301','corriente_lazo','Coriolis emulsión','mA', 4,  20,  3.8,20.5,'4-20 mA','simulado'),
 (1,'FRE_cau_emulsion_out',   'Frecuencia Coriolis emulsión', 'TK-301','frecuencia', 'Coriolis emulsión', 'Hz',   NULL,NULL,NULL,NULL,'directa','simulado'),
 (1,'AMP_niv_emulsion_dep',   'Lazo radar emulsión',          'TK-301','corriente_lazo','Radar TK-301',   'mA',   4,  20,  NULL,NULL,'4-20 mA','simulado'),
 (1,'DIS_niv_emulsion_dep',   'Distancia radar emulsión',     'TK-301','distancia',  'Radar TK-301',      'm',    0,  15,  NULL,NULL,'directa','simulado'),
 (1,'AMP_eco_emulsion_dep',   'Eco radar emulsión',           'TK-301','eco',        'Radar TK-301',      'dB',   NULL,NULL,25, 80,  'directa','simulado'),
 (1,'RPM_motor_molino',       'Velocidad del motor',          'MC-01', 'velocidad',  'Variador MC-01',    'RPM',  0,  3000,NULL,NULL,'directa','simulado'),
 (1,'FRE_vfd_motor_molino',   'Frecuencia variador',          'MC-01', 'frecuencia', 'Variador MC-01',    'Hz',   0,  60,  NULL,NULL,'directa','simulado'),
 (1,'AMP_vfd_motor_molino',   'Corriente del motor',          'MC-01', 'corriente',  'Variador MC-01',    'A',    0,  200, 0,  125, 'directa','simulado'),
 (1,'TOR_vfd_motor_molino',   'Torque del motor',             'MC-01', 'torque',     'Variador MC-01',    '%',    0,  150, NULL,NULL,'directa','simulado'),
 (1,'VIB_vel_motor_molino',   'Vibración del motor',          'MC-01', 'vibracion',  'Sensor de vibración','mm/s',0,  25,  0,  4.5, '4-20 mA','simulado'),
 (1,'AMP_vib_motor_molino',   'Lazo vibración',               'MC-01', 'corriente_lazo','Sensor de vibración','mA',4, 20,  NULL,NULL,'4-20 mA','simulado'),
 (1,'CAU_bomba_lpm',          'Caudal de la bomba',           'P-101', 'caudal',     'Bomba P-101',       'L/min',0,  300, NULL,NULL,'directa','simulado'),
 (1,'PRE_dif_filtro_bar',     'Presión diferencial filtro',   'F-101', 'presion',    'Transmisor ΔP F-101','bar', 0,  3,   0,  1.0, '4-20 mA','simulado'),
 (1,'POS_valvula_3vias',      'Posición válvula 3 vías',      'V-101', 'posicion',   'Válvula V-101',     '0/1',  NULL,NULL,NULL,NULL,'digital','simulado'),
 (1,'VAL_aire_linea',         'Línea de aire',                'V-101', 'posicion',   'Válvula de aire',   '0/1',  NULL,NULL,NULL,NULL,'digital','simulado'),
 (1,'TEM_emulsion_molino_out','Temperatura salida molino',    'MC-01', 'temperatura','Sensor salida MC-01','°C',  0,  150, NULL,NULL,'4-20 mA','simulado'),
 (1,'PRE_intercambiador_bar', 'Presión intercambiador',       'E-301', 'presion',    'Transmisor E-301',  'bar',  0,  6,   0,  3.6, '4-20 mA','simulado');

-- 7c. Usuarios de prueba, uno por rol. Clave inicial: Qla.2026!
--     Todos deben cambiarla en el primer ingreso. Bórralos antes de entregar.
INSERT INTO usuarios (rol_id, nombre, email, password_hash)
SELECT r.id, u.nombre, u.email, crypt('Qla.2026!', gen_salt('bf', 10))
FROM (VALUES
  ('administrador', 'Administrador de prueba', 'admin@demo.qla.cl'),
  ('supervisor',    'Supervisor de prueba',    'supervisor@demo.qla.cl'),
  ('operador',      'Operador de prueba',      'operador@demo.qla.cl'),
  ('visualizador',  'Visualizador de prueba',  'visor@demo.qla.cl')
) AS u(rol, nombre, email)
JOIN roles r ON r.nombre = u.rol;

COMMIT;

-- =====================================================================
-- COMPROBACIÓN (ejecutar después)
--   SELECT r.nombre, u.email FROM mantpred.usuarios u JOIN mantpred.roles r ON r.id = u.rol_id;
--   SELECT origen, count(*) FROM mantpred.sensores GROUP BY origen;   -- real 6, simulado 41
--   -- Verificar una clave (devuelve true):
--   SELECT password_hash = extensions.crypt('Qla.2026!', password_hash)
--   FROM mantpred.usuarios WHERE email = 'admin@demo.qla.cl';
--
-- NOTAS
-- * Supabase no expone el esquema mantpred por su API pública: solo tu
--   backend (conexión como postgres) puede leerlo. Es lo que queremos.
-- * Tamaño: cada lectura ocupa ~170 bytes con índices (medido). Plan gratis = 500 MB.
--   41 sensores simulados x 1.440 min x 14 días ≈ 0,83 M filas ≈ 140 MB.
--   El año simulado completo va a S3, no aquí.
-- * Las contraseñas se generan con bcrypt; la librería bcrypt de Python
--   las verifica sin cambios.
-- =====================================================================
