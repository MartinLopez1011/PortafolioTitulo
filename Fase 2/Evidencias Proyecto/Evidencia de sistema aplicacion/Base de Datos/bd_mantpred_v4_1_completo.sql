-- =====================================================================
-- Proyecto : Mantenimiento predictivo inteligente – Química Latinoamericana S.A.
-- Archivo  : bd_mantpred_v4_1_completo.sql
-- Qué es   : el esquema FINAL (v4.1) en un solo archivo, para crear la base
--            desde cero (por ejemplo, una RDS nueva).
--
-- Equivale a ejecutar, en orden:
--   bd_mantenimiento_predictivo_v2.sql -> migracion_v3.sql -> migracion_v4.sql
--   -> migracion_v4_1.sql
-- (esos archivos siguen en el repositorio como historial de cómo evolucionó
--  la base; para una base ya existente se usan las migraciones).
--
-- Contiene: 16 tablas, restricciones (PK, FK, UNIQUE, CHECK), índices,
-- comentarios, RLS y los datos iniciales de catálogo: 1 equipo, 11 componentes,
-- 47 sensores, 8 tipos de falla, 432 rangos de operación, 8 reglas de alarma,
-- 2 roles y la bitácora de mantenciones del año simulado (60 + 107 vínculos).
--
-- NO contiene usuarios: después de cargarlo, crear el administrador con
--   python crear_admin.py --env "<archivo con DATABASE_URL>"
-- Tampoco datos de series de tiempo (lecturas, predicciones, alarmas): los
-- genera el sistema.
--
-- Uso (falla si el esquema mantpred ya existe, para no sobrescribir nada):
--   python ejecutar_sql.py bd_mantpred_v4_1_completo.sql --env "<archivo .env>"
-- Se ejecuta en una sola transacción: si algo falla no se aplica nada.
-- Generado con pg_dump desde una base construida con las 4 migraciones.
-- =====================================================================

BEGIN;

-- pgcrypto (crypt / gen_salt) se usa para cifrar las claves con bcrypt
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- ---------------------------------------------------------------------
-- 1. ESTRUCTURA
-- ---------------------------------------------------------------------
--
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: mantpred; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA mantpred;

--
-- Name: SCHEMA mantpred; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA mantpred IS 'Mantenimiento predictivo del molino coloidal MC-01 de Química Latinoamericana';

--
-- Name: purgar_datos_simulados(integer); Type: FUNCTION; Schema: mantpred; Owner: -
--

CREATE FUNCTION mantpred.purgar_datos_simulados(dias integer) RETURNS TABLE(tabla text, filas bigint)
    LANGUAGE plpgsql
    AS $$
DECLARE limite TIMESTAMPTZ;
BEGIN
    SELECT max(ts) - make_interval(days => dias) INTO limite
    FROM mantpred.lecturas WHERE fuente = 'simulado';
    IF limite IS NULL THEN RETURN; END IF;

    DELETE FROM mantpred.lecturas WHERE fuente = 'simulado' AND ts < limite;
    GET DIAGNOSTICS filas = ROW_COUNT; tabla := 'lecturas'; RETURN NEXT;
    DELETE FROM mantpred.estados_equipo WHERE fuente = 'simulado' AND ts < limite;
    GET DIAGNOSTICS filas = ROW_COUNT; tabla := 'estados_equipo'; RETURN NEXT;
    DELETE FROM mantpred.predicciones WHERE fuente = 'simulado' AND ts < limite;
    GET DIAGNOSTICS filas = ROW_COUNT; tabla := 'predicciones'; RETURN NEXT;
    DELETE FROM mantpred.condiciones_minuto WHERE fuente = 'simulado' AND ts < limite;
    GET DIAGNOSTICS filas = ROW_COUNT; tabla := 'condiciones_minuto'; RETURN NEXT;
END $$;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alarmas; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.alarmas (
    id bigint NOT NULL,
    equipo_id integer NOT NULL,
    origen character varying(10) NOT NULL,
    tipo_falla_id smallint,
    inicio timestamp with time zone NOT NULL,
    fin timestamp with time zone,
    valor numeric(12,3),
    severidad character varying(12) NOT NULL,
    mensaje character varying(250),
    fuente character varying(10) DEFAULT 'real'::character varying NOT NULL,
    reconocida_por integer,
    reconocida_en timestamp with time zone,
    comentario character varying(250),
    regla_id smallint,
    clave character varying(80) NOT NULL,
    detalle jsonb,
    CONSTRAINT alarmas_check CHECK (((reconocida_por IS NULL) = (reconocida_en IS NULL))),
    CONSTRAINT alarmas_check1 CHECK (((fin IS NULL) OR (fin >= inicio))),
    CONSTRAINT alarmas_check3 CHECK ((((origen)::text <> 'modelo'::text) OR (tipo_falla_id IS NOT NULL))),
    CONSTRAINT alarmas_fuente_check CHECK (((fuente)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[]))),
    CONSTRAINT alarmas_origen_check CHECK (((origen)::text = ANY ((ARRAY['regla'::character varying, 'modelo'::character varying])::text[]))),
    CONSTRAINT alarmas_regla_check CHECK ((((origen)::text <> 'regla'::text) OR ((regla_id IS NOT NULL) AND (tipo_falla_id IS NULL)))),
    CONSTRAINT alarmas_severidad_check CHECK (((severidad)::text = ANY ((ARRAY['aviso'::character varying, 'advertencia'::character varying, 'critica'::character varying])::text[])))
);

--
-- Name: TABLE alarmas; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.alarmas IS 'Alarmas abiertas y cerradas. Origen modelo (tipo_falla_id) o regla (regla_id). Una sola activa por clave';

--
-- Name: COLUMN alarmas.clave; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON COLUMN mantpred.alarmas.clave IS 'Condición que la originó: modelo:<falla> o regla:<código>';

--
-- Name: COLUMN alarmas.detalle; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON COLUMN mantpred.alarmas.detalle IS 'Origen en palabras y sensores señalados por el autoencoder';

--
-- Name: alarmas_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.alarmas ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.alarmas_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: auditoria_accesos; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.auditoria_accesos (
    id bigint NOT NULL,
    usuario_id integer,
    email character varying(150),
    fecha timestamp with time zone DEFAULT now() NOT NULL,
    ip inet,
    accion character varying(50) NOT NULL,
    detalle character varying(250)
);

--
-- Name: TABLE auditoria_accesos; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.auditoria_accesos IS 'Registro de ingresos y acciones administrativas';

--
-- Name: auditoria_accesos_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.auditoria_accesos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.auditoria_accesos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: componentes; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.componentes (
    id smallint NOT NULL,
    equipo_id integer NOT NULL,
    codigo character varying(20) NOT NULL,
    nombre character varying(80) NOT NULL,
    tipo character varying(20) NOT NULL,
    CONSTRAINT componentes_tipo_check CHECK (((tipo)::text = ANY ((ARRAY['estanque'::character varying, 'instrumento'::character varying, 'filtro'::character varying, 'bomba'::character varying, 'valvula'::character varying, 'molino'::character varying, 'intercambiador'::character varying])::text[])))
);

--
-- Name: TABLE componentes; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.componentes IS 'Partes de la línea del equipo (estanques, instrumentos, filtro, bomba, válvula, molino, intercambiador), identificadas por su tag de planta';

--
-- Name: componentes_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.componentes ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.componentes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: condiciones_minuto; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.condiciones_minuto (
    equipo_id integer NOT NULL,
    fuente character varying(10) NOT NULL,
    ts timestamp with time zone NOT NULL,
    clave character varying(80) NOT NULL,
    origen character varying(10) NOT NULL,
    tipo_falla_id smallint,
    regla_id smallint,
    valor numeric(14,4),
    CONSTRAINT condiciones_minuto_fuente_check CHECK (((fuente)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[]))),
    CONSTRAINT condiciones_minuto_origen_check CHECK (((origen)::text = ANY ((ARRAY['modelo'::character varying, 'regla'::character varying])::text[])))
);

--
-- Name: TABLE condiciones_minuto; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.condiciones_minuto IS 'Condiciones de alarma que se cumplieron cada minuto (modelo o regla). Base de la regla 3 de 5';

--
-- Name: equipos; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.equipos (
    id integer NOT NULL,
    codigo character varying(20) NOT NULL,
    nombre character varying(100) NOT NULL,
    tipo character varying(60) NOT NULL,
    marca character varying(60),
    modelo character varying(60),
    potencia character varying(40),
    ubicacion character varying(120)
);

--
-- Name: TABLE equipos; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.equipos IS 'Equipos monitoreados. Hoy, el molino coloidal MC-01';

--
-- Name: equipos_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.equipos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.equipos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: estados_equipo; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.estados_equipo (
    id bigint NOT NULL,
    equipo_id integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    estado character varying(15) NOT NULL,
    tipo_asfalto character varying(15),
    fuente character varying(10) DEFAULT 'real'::character varying NOT NULL,
    CONSTRAINT estados_equipo_estado_check CHECK (((estado)::text = ANY ((ARRAY['detenida'::character varying, 'preparacion'::character varying, 'produccion'::character varying, 'espera'::character varying, 'limpieza'::character varying, 'mantenimiento'::character varying, 'falla'::character varying])::text[]))),
    CONSTRAINT estados_equipo_fuente_check CHECK (((fuente)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[]))),
    CONSTRAINT estados_equipo_tipo_asfalto_check CHECK (((tipo_asfalto)::text = ANY ((ARRAY['convencional'::character varying, 'plastomerico'::character varying, 'ninguno'::character varying])::text[])))
);

--
-- Name: TABLE estados_equipo; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.estados_equipo IS 'Modo de operación del equipo por minuto (producción, limpieza, espera, preparación, detenida) y tipo de asfalto';

--
-- Name: estados_equipo_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.estados_equipo ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.estados_equipo_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: lecturas; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.lecturas (
    id bigint NOT NULL,
    sensor_id integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    valor numeric(12,3),
    calidad character varying(10) DEFAULT 'buena'::character varying NOT NULL,
    fuente character varying(10) DEFAULT 'real'::character varying NOT NULL,
    CONSTRAINT lecturas_calidad_check CHECK (((calidad)::text = ANY ((ARRAY['buena'::character varying, 'dudosa'::character varying, 'mala'::character varying])::text[]))),
    CONSTRAINT lecturas_fuente_check CHECK (((fuente)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[])))
);

--
-- Name: TABLE lecturas; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.lecturas IS 'Valor de cada sensor por minuto. Una fila por sensor, fuente y minuto';

--
-- Name: COLUMN lecturas.fuente; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON COLUMN mantpred.lecturas.fuente IS 'simulado (dataset) o real (planta)';

--
-- Name: lecturas_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.lecturas ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.lecturas_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: mantenimiento_fallas; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.mantenimiento_fallas (
    mantenimiento_id integer NOT NULL,
    tipo_falla_id smallint NOT NULL
);

--
-- Name: TABLE mantenimiento_fallas; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.mantenimiento_fallas IS 'Modos de falla que atiende cada intervención: una correctiva atiende uno; una preventiva, varios';

--
-- Name: mantenimientos; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.mantenimientos (
    id integer NOT NULL,
    equipo_id integer NOT NULL,
    registrado_por integer,
    tipo character varying(12) NOT NULL,
    alarma_id bigint,
    fecha_inicio timestamp with time zone NOT NULL,
    fecha_fin timestamp with time zone,
    descripcion text,
    fuente character varying(10) DEFAULT 'real'::character varying NOT NULL,
    origen_registro character varying(10) DEFAULT 'dashboard'::character varying NOT NULL,
    componente_id smallint,
    CONSTRAINT mantenimientos_check CHECK (((fecha_fin IS NULL) OR (fecha_fin >= fecha_inicio))),
    CONSTRAINT mantenimientos_fuente_check CHECK (((fuente)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[]))),
    CONSTRAINT mantenimientos_origen_registro_check CHECK (((origen_registro)::text = ANY ((ARRAY['bitacora'::character varying, 'dashboard'::character varying])::text[]))),
    CONSTRAINT mantenimientos_tipo_check CHECK (((tipo)::text = ANY ((ARRAY['preventivo'::character varying, 'correctivo'::character varying, 'predictivo'::character varying])::text[])))
);

--
-- Name: TABLE mantenimientos; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.mantenimientos IS 'Bitácora de intervenciones de la planta. componente_id NULL = intervención de toda la línea (preventiva mensual)';

--
-- Name: mantenimientos_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.mantenimientos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.mantenimientos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: predicciones; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.predicciones (
    id bigint NOT NULL,
    equipo_id integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    modelo character varying(15) NOT NULL,
    modelo_version character varying(30) NOT NULL,
    horizonte character varying(6) DEFAULT 'actual'::character varying NOT NULL,
    tipo_falla_id smallint,
    prob_falla numeric(5,4),
    indice_salud numeric(8,2),
    fuente character varying(10) DEFAULT 'real'::character varying NOT NULL,
    metodo character varying(20),
    umbral numeric(10,4),
    alerta boolean DEFAULT false NOT NULL,
    dias_estimados numeric(10,2),
    error_ae numeric(14,4),
    detalle jsonb,
    CONSTRAINT predicciones_autoencoder_check CHECK ((((modelo)::text <> 'autoencoder'::text) OR ((tipo_falla_id IS NULL) AND (prob_falla IS NULL)))),
    CONSTRAINT predicciones_diagnostico_check CHECK ((((modelo)::text <> 'diagnostico'::text) OR (error_ae IS NULL))),
    CONSTRAINT predicciones_fuente_check CHECK (((fuente)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[]))),
    CONSTRAINT predicciones_horizonte_check CHECK (((horizonte)::text = ANY ((ARRAY['actual'::character varying, '24h'::character varying, '5d'::character varying, '15d'::character varying])::text[]))),
    CONSTRAINT predicciones_horizonte_modelo_check CHECK ((((modelo)::text = 'predictivo'::text) = ((horizonte)::text <> 'actual'::text))),
    CONSTRAINT predicciones_modelo_check CHECK (((modelo)::text = ANY ((ARRAY['diagnostico'::character varying, 'autoencoder'::character varying, 'predictivo'::character varying])::text[]))),
    CONSTRAINT predicciones_predictivo_check CHECK ((((modelo)::text <> 'predictivo'::text) OR (tipo_falla_id IS NOT NULL))),
    CONSTRAINT predicciones_prob_falla_check CHECK (((prob_falla >= (0)::numeric) AND (prob_falla <= (1)::numeric)))
);

--
-- Name: TABLE predicciones; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.predicciones IS 'Resultados de los 3 modelos. diagnostico y autoencoder: uno por minuto (horizonte actual). predictivo: uno por hora, falla y horizonte (24h, 5d, 15d)';

--
-- Name: COLUMN predicciones.metodo; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON COLUMN mantpred.predicciones.metodo IS 'LightGBM o Tendencia (predictivo); Autoencoder (vigilancia)';

--
-- Name: COLUMN predicciones.dias_estimados; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON COLUMN mantpred.predicciones.dias_estimados IS 'Días hasta cruzar el límite físico, en las fallas raras (método Tendencia)';

--
-- Name: COLUMN predicciones.error_ae; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON COLUMN mantpred.predicciones.error_ae IS 'Error de reconstrucción (MSE) del autoencoder';

--
-- Name: predicciones_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.predicciones ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.predicciones_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: rangos_operacion; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.rangos_operacion (
    id integer NOT NULL,
    sensor_id integer NOT NULL,
    estado character varying(15) NOT NULL,
    tipo_asfalto character varying(15) NOT NULL,
    normal_min numeric(12,3) NOT NULL,
    normal_max numeric(12,3) NOT NULL,
    CONSTRAINT rangos_operacion_check CHECK ((normal_min <= normal_max)),
    CONSTRAINT rangos_operacion_estado_check CHECK (((estado)::text = ANY ((ARRAY['detenida'::character varying, 'preparacion'::character varying, 'produccion'::character varying, 'espera'::character varying, 'limpieza'::character varying, 'mantenimiento'::character varying])::text[]))),
    CONSTRAINT rangos_operacion_tipo_asfalto_check CHECK (((tipo_asfalto)::text = ANY ((ARRAY['convencional'::character varying, 'plastomerico'::character varying, 'ninguno'::character varying])::text[])))
);

--
-- Name: TABLE rangos_operacion; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.rangos_operacion IS 'Banda normal de cada sensor según modo de operación y tipo de asfalto (percentiles 2,5 y 97,5 de la operación sana)';

--
-- Name: rangos_operacion_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.rangos_operacion ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.rangos_operacion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: reglas_alarma; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.reglas_alarma (
    id smallint NOT NULL,
    codigo character varying(40) NOT NULL,
    sensor_id integer NOT NULL,
    comparacion character(1) NOT NULL,
    limite numeric(12,3) NOT NULL,
    tipo_asfalto character varying(15),
    solo_en_marcha boolean NOT NULL,
    prioridad character varying(10) NOT NULL,
    mensaje character varying(120) NOT NULL,
    accion character varying(250),
    activa boolean DEFAULT true NOT NULL,
    CONSTRAINT reglas_alarma_comparacion_check CHECK ((comparacion = ANY (ARRAY['>'::bpchar, '<'::bpchar]))),
    CONSTRAINT reglas_alarma_prioridad_check CHECK (((prioridad)::text = ANY ((ARRAY['baja'::character varying, 'media'::character varying, 'alta'::character varying])::text[]))),
    CONSTRAINT reglas_alarma_tipo_asfalto_check CHECK (((tipo_asfalto)::text = ANY ((ARRAY['convencional'::character varying, 'plastomerico'::character varying])::text[])))
);

--
-- Name: TABLE reglas_alarma; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.reglas_alarma IS 'Reglas fijas sobre un sensor: límites de instrumento y de proceso';

--
-- Name: reglas_alarma_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.reglas_alarma ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.reglas_alarma_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: roles; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.roles (
    id smallint NOT NULL,
    nombre character varying(30) NOT NULL,
    nivel smallint NOT NULL,
    descripcion character varying(200),
    CONSTRAINT roles_nivel_check CHECK (((nivel >= 1) AND (nivel <= 4))),
    CONSTRAINT roles_nombre_check CHECK (((nombre)::text = ANY ((ARRAY['administrador'::character varying, 'operador'::character varying])::text[])))
);

--
-- Name: TABLE roles; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.roles IS 'Roles del sistema: operador (nivel 2) y administrador (nivel 4)';

--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.roles ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: sensores; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.sensores (
    id integer NOT NULL,
    equipo_id integer NOT NULL,
    tag character varying(40) NOT NULL,
    nombre character varying(80) NOT NULL,
    variable character varying(40) NOT NULL,
    tipo_sensor character varying(80) NOT NULL,
    unidad character varying(15) NOT NULL,
    rango_min numeric(12,3),
    rango_max numeric(12,3),
    normal_min numeric(12,3),
    normal_max numeric(12,3),
    senal character varying(20) DEFAULT '4-20 mA'::character varying NOT NULL,
    origen character varying(10) DEFAULT 'real'::character varying NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    descripcion character varying(250),
    componente_id smallint NOT NULL,
    CONSTRAINT sensores_check CHECK (((rango_min IS NULL) OR (rango_max IS NULL) OR (rango_min < rango_max))),
    CONSTRAINT sensores_check1 CHECK (((normal_min IS NULL) OR (normal_max IS NULL) OR (normal_min <= normal_max))),
    CONSTRAINT sensores_origen_check CHECK (((origen)::text = ANY ((ARRAY['real'::character varying, 'simulado'::character varying])::text[])))
);

--
-- Name: TABLE sensores; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.sensores IS 'Catálogo de señales medidas: 41 del dataset simulado y 6 tags reales del PLC. normal_min/normal_max = banda general cuando no hay banda por modo en rangos_operacion';

--
-- Name: sensores_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.sensores ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.sensores_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: tipos_falla; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.tipos_falla (
    id smallint NOT NULL,
    codigo character varying(60) NOT NULL,
    titulo character varying(100) NOT NULL,
    prioridad character varying(10) NOT NULL,
    accion character varying(250),
    componente_id smallint,
    CONSTRAINT tipos_falla_prioridad_check CHECK (((prioridad)::text = ANY ((ARRAY['baja'::character varying, 'media'::character varying, 'alta'::character varying])::text[])))
);

--
-- Name: TABLE tipos_falla; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.tipos_falla IS 'Modos de falla que reconocen los modelos: 7 fallas y la anomalía desconocida';

--
-- Name: tipos_falla_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.tipos_falla ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.tipos_falla_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: usuarios; Type: TABLE; Schema: mantpred; Owner: -
--

CREATE TABLE mantpred.usuarios (
    id integer NOT NULL,
    rol_id smallint NOT NULL,
    nombre character varying(120) NOT NULL,
    email character varying(150) NOT NULL,
    password_hash character varying(255) NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    debe_cambiar_clave boolean DEFAULT true NOT NULL,
    intentos_fallidos smallint DEFAULT 0 NOT NULL,
    bloqueado_hasta timestamp with time zone,
    ultimo_acceso timestamp with time zone,
    creado_en timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: TABLE usuarios; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON TABLE mantpred.usuarios IS 'Usuarios del dashboard. Clave con bcrypt, bloqueo por intentos fallidos';

--
-- Name: usuarios_id_seq; Type: SEQUENCE; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.usuarios ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME mantpred.usuarios_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: alarmas alarmas_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.alarmas
    ADD CONSTRAINT alarmas_pkey PRIMARY KEY (id);

--
-- Name: auditoria_accesos auditoria_accesos_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.auditoria_accesos
    ADD CONSTRAINT auditoria_accesos_pkey PRIMARY KEY (id);

--
-- Name: componentes componentes_codigo_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.componentes
    ADD CONSTRAINT componentes_codigo_key UNIQUE (codigo);

--
-- Name: componentes componentes_id_equipo_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.componentes
    ADD CONSTRAINT componentes_id_equipo_key UNIQUE (id, equipo_id);

--
-- Name: componentes componentes_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.componentes
    ADD CONSTRAINT componentes_pkey PRIMARY KEY (id);

--
-- Name: condiciones_minuto condiciones_minuto_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.condiciones_minuto
    ADD CONSTRAINT condiciones_minuto_pkey PRIMARY KEY (equipo_id, fuente, ts, clave);

--
-- Name: equipos equipos_codigo_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.equipos
    ADD CONSTRAINT equipos_codigo_key UNIQUE (codigo);

--
-- Name: equipos equipos_nombre_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.equipos
    ADD CONSTRAINT equipos_nombre_key UNIQUE (nombre);

--
-- Name: equipos equipos_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.equipos
    ADD CONSTRAINT equipos_pkey PRIMARY KEY (id);

--
-- Name: estados_equipo estados_equipo_equipo_id_fuente_ts_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.estados_equipo
    ADD CONSTRAINT estados_equipo_equipo_id_fuente_ts_key UNIQUE (equipo_id, fuente, ts);

--
-- Name: estados_equipo estados_equipo_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.estados_equipo
    ADD CONSTRAINT estados_equipo_pkey PRIMARY KEY (id);

--
-- Name: lecturas lecturas_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.lecturas
    ADD CONSTRAINT lecturas_pkey PRIMARY KEY (id);

--
-- Name: lecturas lecturas_sensor_id_fuente_ts_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.lecturas
    ADD CONSTRAINT lecturas_sensor_id_fuente_ts_key UNIQUE (sensor_id, fuente, ts);

--
-- Name: mantenimiento_fallas mantenimiento_fallas_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimiento_fallas
    ADD CONSTRAINT mantenimiento_fallas_pkey PRIMARY KEY (mantenimiento_id, tipo_falla_id);

--
-- Name: mantenimientos mantenimientos_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimientos
    ADD CONSTRAINT mantenimientos_pkey PRIMARY KEY (id);

--
-- Name: predicciones predicciones_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.predicciones
    ADD CONSTRAINT predicciones_pkey PRIMARY KEY (id);

--
-- Name: rangos_operacion rangos_operacion_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.rangos_operacion
    ADD CONSTRAINT rangos_operacion_pkey PRIMARY KEY (id);

--
-- Name: rangos_operacion rangos_operacion_sensor_id_estado_tipo_asfalto_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.rangos_operacion
    ADD CONSTRAINT rangos_operacion_sensor_id_estado_tipo_asfalto_key UNIQUE (sensor_id, estado, tipo_asfalto);

--
-- Name: reglas_alarma reglas_alarma_codigo_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.reglas_alarma
    ADD CONSTRAINT reglas_alarma_codigo_key UNIQUE (codigo);

--
-- Name: reglas_alarma reglas_alarma_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.reglas_alarma
    ADD CONSTRAINT reglas_alarma_pkey PRIMARY KEY (id);

--
-- Name: roles roles_nivel_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.roles
    ADD CONSTRAINT roles_nivel_key UNIQUE (nivel);

--
-- Name: roles roles_nombre_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.roles
    ADD CONSTRAINT roles_nombre_key UNIQUE (nombre);

--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);

--
-- Name: sensores sensores_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.sensores
    ADD CONSTRAINT sensores_pkey PRIMARY KEY (id);

--
-- Name: sensores sensores_tag_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.sensores
    ADD CONSTRAINT sensores_tag_key UNIQUE (tag);

--
-- Name: tipos_falla tipos_falla_codigo_key; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.tipos_falla
    ADD CONSTRAINT tipos_falla_codigo_key UNIQUE (codigo);

--
-- Name: tipos_falla tipos_falla_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.tipos_falla
    ADD CONSTRAINT tipos_falla_pkey PRIMARY KEY (id);

--
-- Name: usuarios usuarios_pkey; Type: CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.usuarios
    ADD CONSTRAINT usuarios_pkey PRIMARY KEY (id);

--
-- Name: ix_alarmas_activas; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_alarmas_activas ON mantpred.alarmas USING btree (equipo_id) WHERE (fin IS NULL);

--
-- Name: ix_alarmas_equipo_inicio; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_alarmas_equipo_inicio ON mantpred.alarmas USING btree (equipo_id, inicio DESC);

--
-- Name: ix_alarmas_fuente_inicio; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_alarmas_fuente_inicio ON mantpred.alarmas USING btree (fuente, inicio DESC);

--
-- Name: ix_alarmas_pendientes; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_alarmas_pendientes ON mantpred.alarmas USING btree (inicio DESC) WHERE (reconocida_en IS NULL);

--
-- Name: ix_auditoria_usuario_fecha; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_auditoria_usuario_fecha ON mantpred.auditoria_accesos USING btree (usuario_id, fecha DESC);

--
-- Name: ix_lecturas_ts; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_lecturas_ts ON mantpred.lecturas USING btree (ts);

--
-- Name: ix_mant_equipo_fecha; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_mant_equipo_fecha ON mantpred.mantenimientos USING btree (equipo_id, fecha_inicio DESC);

--
-- Name: ix_mant_fallas_falla; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_mant_fallas_falla ON mantpred.mantenimiento_fallas USING btree (tipo_falla_id);

--
-- Name: ix_mantenimientos_componente; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_mantenimientos_componente ON mantpred.mantenimientos USING btree (componente_id);

--
-- Name: ix_pred_equipo_modelo_ts; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_pred_equipo_modelo_ts ON mantpred.predicciones USING btree (equipo_id, fuente, modelo, ts DESC);

--
-- Name: ix_sensores_componente; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_sensores_componente ON mantpred.sensores USING btree (componente_id);

--
-- Name: ix_sensores_equipo; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_sensores_equipo ON mantpred.sensores USING btree (equipo_id);

--
-- Name: ix_usuarios_rol; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE INDEX ix_usuarios_rol ON mantpred.usuarios USING btree (rol_id);

--
-- Name: ux_alarma_activa; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE UNIQUE INDEX ux_alarma_activa ON mantpred.alarmas USING btree (equipo_id, fuente, clave) WHERE (fin IS NULL);

--
-- Name: ux_pred_predictivo; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE UNIQUE INDEX ux_pred_predictivo ON mantpred.predicciones USING btree (equipo_id, fuente, tipo_falla_id, horizonte, ts) WHERE ((modelo)::text = 'predictivo'::text);

--
-- Name: ux_pred_tiempo_real; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE UNIQUE INDEX ux_pred_tiempo_real ON mantpred.predicciones USING btree (equipo_id, fuente, modelo, ts) WHERE ((modelo)::text = ANY ((ARRAY['diagnostico'::character varying, 'autoencoder'::character varying])::text[]));

--
-- Name: ux_usuarios_email; Type: INDEX; Schema: mantpred; Owner: -
--

CREATE UNIQUE INDEX ux_usuarios_email ON mantpred.usuarios USING btree (lower((email)::text));

--
-- Name: alarmas alarmas_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.alarmas
    ADD CONSTRAINT alarmas_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: alarmas alarmas_reconocida_por_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.alarmas
    ADD CONSTRAINT alarmas_reconocida_por_fkey FOREIGN KEY (reconocida_por) REFERENCES mantpred.usuarios(id);

--
-- Name: alarmas alarmas_regla_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.alarmas
    ADD CONSTRAINT alarmas_regla_id_fkey FOREIGN KEY (regla_id) REFERENCES mantpred.reglas_alarma(id);

--
-- Name: alarmas alarmas_tipo_falla_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.alarmas
    ADD CONSTRAINT alarmas_tipo_falla_id_fkey FOREIGN KEY (tipo_falla_id) REFERENCES mantpred.tipos_falla(id);

--
-- Name: auditoria_accesos auditoria_accesos_usuario_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.auditoria_accesos
    ADD CONSTRAINT auditoria_accesos_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES mantpred.usuarios(id) ON DELETE SET NULL;

--
-- Name: componentes componentes_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.componentes
    ADD CONSTRAINT componentes_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: condiciones_minuto condiciones_minuto_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.condiciones_minuto
    ADD CONSTRAINT condiciones_minuto_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: condiciones_minuto condiciones_minuto_regla_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.condiciones_minuto
    ADD CONSTRAINT condiciones_minuto_regla_id_fkey FOREIGN KEY (regla_id) REFERENCES mantpred.reglas_alarma(id);

--
-- Name: condiciones_minuto condiciones_minuto_tipo_falla_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.condiciones_minuto
    ADD CONSTRAINT condiciones_minuto_tipo_falla_id_fkey FOREIGN KEY (tipo_falla_id) REFERENCES mantpred.tipos_falla(id);

--
-- Name: estados_equipo estados_equipo_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.estados_equipo
    ADD CONSTRAINT estados_equipo_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: lecturas lecturas_sensor_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.lecturas
    ADD CONSTRAINT lecturas_sensor_id_fkey FOREIGN KEY (sensor_id) REFERENCES mantpred.sensores(id);

--
-- Name: mantenimiento_fallas mantenimiento_fallas_mantenimiento_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimiento_fallas
    ADD CONSTRAINT mantenimiento_fallas_mantenimiento_id_fkey FOREIGN KEY (mantenimiento_id) REFERENCES mantpred.mantenimientos(id) ON DELETE CASCADE;

--
-- Name: mantenimiento_fallas mantenimiento_fallas_tipo_falla_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimiento_fallas
    ADD CONSTRAINT mantenimiento_fallas_tipo_falla_id_fkey FOREIGN KEY (tipo_falla_id) REFERENCES mantpred.tipos_falla(id);

--
-- Name: mantenimientos mantenimientos_alarma_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimientos
    ADD CONSTRAINT mantenimientos_alarma_id_fkey FOREIGN KEY (alarma_id) REFERENCES mantpred.alarmas(id);

--
-- Name: mantenimientos mantenimientos_componente_equipo_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimientos
    ADD CONSTRAINT mantenimientos_componente_equipo_fkey FOREIGN KEY (componente_id, equipo_id) REFERENCES mantpred.componentes(id, equipo_id);

--
-- Name: CONSTRAINT mantenimientos_componente_equipo_fkey ON mantenimientos; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON CONSTRAINT mantenimientos_componente_equipo_fkey ON mantpred.mantenimientos IS 'El componente intervenido debe pertenecer al equipo de la mantención (sin componente = toda la línea)';

--
-- Name: mantenimientos mantenimientos_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimientos
    ADD CONSTRAINT mantenimientos_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: mantenimientos mantenimientos_registrado_por_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.mantenimientos
    ADD CONSTRAINT mantenimientos_registrado_por_fkey FOREIGN KEY (registrado_por) REFERENCES mantpred.usuarios(id);

--
-- Name: predicciones predicciones_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.predicciones
    ADD CONSTRAINT predicciones_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: predicciones predicciones_tipo_falla_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.predicciones
    ADD CONSTRAINT predicciones_tipo_falla_id_fkey FOREIGN KEY (tipo_falla_id) REFERENCES mantpred.tipos_falla(id);

--
-- Name: rangos_operacion rangos_operacion_sensor_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.rangos_operacion
    ADD CONSTRAINT rangos_operacion_sensor_id_fkey FOREIGN KEY (sensor_id) REFERENCES mantpred.sensores(id);

--
-- Name: reglas_alarma reglas_alarma_sensor_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.reglas_alarma
    ADD CONSTRAINT reglas_alarma_sensor_id_fkey FOREIGN KEY (sensor_id) REFERENCES mantpred.sensores(id);

--
-- Name: sensores sensores_componente_equipo_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.sensores
    ADD CONSTRAINT sensores_componente_equipo_fkey FOREIGN KEY (componente_id, equipo_id) REFERENCES mantpred.componentes(id, equipo_id);

--
-- Name: CONSTRAINT sensores_componente_equipo_fkey ON sensores; Type: COMMENT; Schema: mantpred; Owner: -
--

COMMENT ON CONSTRAINT sensores_componente_equipo_fkey ON mantpred.sensores IS 'El componente del sensor debe pertenecer al mismo equipo que el sensor';

--
-- Name: sensores sensores_equipo_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.sensores
    ADD CONSTRAINT sensores_equipo_id_fkey FOREIGN KEY (equipo_id) REFERENCES mantpred.equipos(id);

--
-- Name: tipos_falla tipos_falla_componente_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.tipos_falla
    ADD CONSTRAINT tipos_falla_componente_id_fkey FOREIGN KEY (componente_id) REFERENCES mantpred.componentes(id);

--
-- Name: usuarios usuarios_rol_id_fkey; Type: FK CONSTRAINT; Schema: mantpred; Owner: -
--

ALTER TABLE ONLY mantpred.usuarios
    ADD CONSTRAINT usuarios_rol_id_fkey FOREIGN KEY (rol_id) REFERENCES mantpred.roles(id);

--
-- Name: alarmas; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.alarmas ENABLE ROW LEVEL SECURITY;

--
-- Name: auditoria_accesos; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.auditoria_accesos ENABLE ROW LEVEL SECURITY;

--
-- Name: componentes; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.componentes ENABLE ROW LEVEL SECURITY;

--
-- Name: condiciones_minuto; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.condiciones_minuto ENABLE ROW LEVEL SECURITY;

--
-- Name: equipos; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.equipos ENABLE ROW LEVEL SECURITY;

--
-- Name: estados_equipo; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.estados_equipo ENABLE ROW LEVEL SECURITY;

--
-- Name: lecturas; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.lecturas ENABLE ROW LEVEL SECURITY;

--
-- Name: mantenimiento_fallas; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.mantenimiento_fallas ENABLE ROW LEVEL SECURITY;

--
-- Name: mantenimientos; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.mantenimientos ENABLE ROW LEVEL SECURITY;

--
-- Name: predicciones; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.predicciones ENABLE ROW LEVEL SECURITY;

--
-- Name: rangos_operacion; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.rangos_operacion ENABLE ROW LEVEL SECURITY;

--
-- Name: reglas_alarma; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.reglas_alarma ENABLE ROW LEVEL SECURITY;

--
-- Name: roles; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.roles ENABLE ROW LEVEL SECURITY;

--
-- Name: sensores; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.sensores ENABLE ROW LEVEL SECURITY;

--
-- Name: tipos_falla; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.tipos_falla ENABLE ROW LEVEL SECURITY;

--
-- Name: usuarios; Type: ROW SECURITY; Schema: mantpred; Owner: -
--

ALTER TABLE mantpred.usuarios ENABLE ROW LEVEL SECURITY;

--
--

-- ---------------------------------------------------------------------
-- 2. DATOS INICIALES (catálogos y bitácora)
-- ---------------------------------------------------------------------
--
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: equipos; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.equipos OVERRIDING SYSTEM VALUE VALUES
	(1, 'MC-01', 'Molino coloidal HP 240', 'Molino coloidal de emulsión', NULL, NULL, '100 hp, 2.900 RPM', 'Planta de emulsiones, El Salto');

--
-- Data for Name: componentes; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.componentes OVERRIDING SYSTEM VALUE VALUES
	(1, 1, 'TK-101', 'Estanque de betún', 'estanque'),
	(2, 1, 'TK-201', 'Estanque de solución jabonosa', 'estanque'),
	(3, 1, 'TK-301', 'Estanque de emulsión', 'estanque'),
	(4, 1, 'TT-101', 'Sensor Pt100 de temperatura del betún', 'instrumento'),
	(5, 1, 'FT-101', 'Caudalímetro Coriolis de betún', 'instrumento'),
	(6, 1, 'FT-201', 'Caudalímetro Coriolis de solución', 'instrumento'),
	(7, 1, 'F-101', 'Filtro de línea', 'filtro'),
	(8, 1, 'P-101', 'Bomba de la línea', 'bomba'),
	(9, 1, 'V-101', 'Válvula de 3 vías y línea de aire', 'valvula'),
	(10, 1, 'MC-01', 'Molino coloidal', 'molino'),
	(11, 1, 'E-301', 'Intercambiador de calor', 'intercambiador');

--
-- Data for Name: mantenimientos; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.mantenimientos OVERRIDING SYSTEM VALUE VALUES
	(1, 1, NULL, 'preventivo', NULL, '2026-01-03 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(4, 1, NULL, 'preventivo', NULL, '2026-02-07 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; secado y sellado del transmisor de caudal; cambio preventivo de rodamientos por vibración alta', 'simulado', 'bitacora', NULL),
	(9, 1, NULL, 'preventivo', NULL, '2026-03-07 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; mantención de caldera; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(12, 1, NULL, 'preventivo', NULL, '2026-04-04 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; mantención de caldera; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(17, 1, NULL, 'preventivo', NULL, '2026-05-02 18:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; mantención de caldera; cambio preventivo de rodamientos por vibración alta', 'simulado', 'bitacora', NULL),
	(23, 1, NULL, 'preventivo', NULL, '2026-06-06 18:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(28, 1, NULL, 'preventivo', NULL, '2026-07-04 18:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; mantención de caldera; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(35, 1, NULL, 'preventivo', NULL, '2026-08-01 18:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; mantención de caldera; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(41, 1, NULL, 'preventivo', NULL, '2026-09-05 18:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; mantención de caldera; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(45, 1, NULL, 'preventivo', NULL, '2026-10-03 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; mantención de caldera; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(52, 1, NULL, 'preventivo', NULL, '2026-11-07 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(57, 1, NULL, 'preventivo', NULL, '2026-12-05 17:00:00+00', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; lubricación de rodamientos', 'simulado', 'bitacora', NULL),
	(2, 1, NULL, 'correctivo', NULL, '2026-01-27 15:47:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(3, 1, NULL, 'correctivo', NULL, '2026-01-30 16:07:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(5, 1, NULL, 'correctivo', NULL, '2026-02-09 14:53:00+00', NULL, 'Reparación de cableado y borneras de la Pt100', 'simulado', 'bitacora', 4),
	(6, 1, NULL, 'correctivo', NULL, '2026-02-13 21:29:00+00', NULL, 'Reparación de caldera / resistencia de calefacción del betún', 'simulado', 'bitacora', 1),
	(7, 1, NULL, 'correctivo', NULL, '2026-02-20 19:51:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(8, 1, NULL, 'correctivo', NULL, '2026-02-26 16:18:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(10, 1, NULL, 'correctivo', NULL, '2026-03-30 15:49:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(11, 1, NULL, 'correctivo', NULL, '2026-03-30 18:03:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(13, 1, NULL, 'correctivo', NULL, '2026-04-06 14:11:00+00', NULL, 'Reparación de caldera / resistencia de calefacción del betún', 'simulado', 'bitacora', 1),
	(14, 1, NULL, 'correctivo', NULL, '2026-04-22 23:10:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(15, 1, NULL, 'correctivo', NULL, '2026-04-27 13:50:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(16, 1, NULL, 'correctivo', NULL, '2026-04-30 23:10:00+00', NULL, 'Limpieza química del intercambiador', 'simulado', 'bitacora', 11),
	(18, 1, NULL, 'correctivo', NULL, '2026-05-05 23:17:00+00', NULL, 'Cambio de transmisor de caudal de solución por cortocircuito', 'simulado', 'bitacora', 6),
	(19, 1, NULL, 'correctivo', NULL, '2026-05-27 15:54:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(20, 1, NULL, 'correctivo', NULL, '2026-05-27 21:46:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(21, 1, NULL, 'correctivo', NULL, '2026-06-02 22:11:00+00', NULL, 'Limpieza química del intercambiador', 'simulado', 'bitacora', 11),
	(22, 1, NULL, 'correctivo', NULL, '2026-06-03 14:43:00+00', NULL, 'Reparación de cableado y borneras de la Pt100', 'simulado', 'bitacora', 4),
	(24, 1, NULL, 'correctivo', NULL, '2026-06-09 20:12:00+00', NULL, 'Cambio de transmisor de caudal de solución por cortocircuito', 'simulado', 'bitacora', 6),
	(25, 1, NULL, 'correctivo', NULL, '2026-06-12 00:46:00+00', NULL, 'Reparación de caldera / resistencia de calefacción del betún', 'simulado', 'bitacora', 1),
	(26, 1, NULL, 'correctivo', NULL, '2026-06-19 20:48:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(27, 1, NULL, 'correctivo', NULL, '2026-06-29 15:06:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(29, 1, NULL, 'correctivo', NULL, '2026-07-13 15:41:00+00', NULL, 'Reparación de cableado y borneras de la Pt100', 'simulado', 'bitacora', 4),
	(30, 1, NULL, 'correctivo', NULL, '2026-07-15 16:07:00+00', NULL, 'Cambio de transmisor de caudal de solución por cortocircuito', 'simulado', 'bitacora', 6),
	(31, 1, NULL, 'correctivo', NULL, '2026-07-21 18:37:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(32, 1, NULL, 'correctivo', NULL, '2026-07-28 16:44:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(33, 1, NULL, 'correctivo', NULL, '2026-07-29 16:16:00+00', NULL, 'Cambio de rodamientos del molino', 'simulado', 'bitacora', 10),
	(34, 1, NULL, 'correctivo', NULL, '2026-07-31 17:42:00+00', NULL, 'Limpieza química del intercambiador', 'simulado', 'bitacora', 11),
	(36, 1, NULL, 'correctivo', NULL, '2026-08-17 16:45:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(37, 1, NULL, 'correctivo', NULL, '2026-08-18 14:48:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(38, 1, NULL, 'correctivo', NULL, '2026-08-24 22:34:00+00', NULL, 'Cambio de transmisor de caudal de solución por cortocircuito', 'simulado', 'bitacora', 6),
	(47, 1, NULL, 'correctivo', NULL, '2026-10-21 19:34:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(39, 1, NULL, 'correctivo', NULL, '2026-08-27 20:17:00+00', NULL, 'Limpieza química del intercambiador', 'simulado', 'bitacora', 11),
	(40, 1, NULL, 'correctivo', NULL, '2026-09-04 17:46:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(42, 1, NULL, 'correctivo', NULL, '2026-09-21 14:33:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(43, 1, NULL, 'correctivo', NULL, '2026-09-24 16:48:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(44, 1, NULL, 'correctivo', NULL, '2026-10-01 20:02:00+00', NULL, 'Cambio de rodamientos del molino', 'simulado', 'bitacora', 10),
	(46, 1, NULL, 'correctivo', NULL, '2026-10-05 15:49:00+00', NULL, 'Reparación de caldera / resistencia de calefacción del betún', 'simulado', 'bitacora', 1),
	(48, 1, NULL, 'correctivo', NULL, '2026-10-28 14:29:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1);
INSERT INTO mantpred.mantenimientos OVERRIDING SYSTEM VALUE VALUES
	(49, 1, NULL, 'correctivo', NULL, '2026-10-28 22:14:00+00', NULL, 'Limpieza química del intercambiador', 'simulado', 'bitacora', 11),
	(50, 1, NULL, 'correctivo', NULL, '2026-11-03 18:43:00+00', NULL, 'Reparación de caldera / resistencia de calefacción del betún', 'simulado', 'bitacora', 1),
	(51, 1, NULL, 'correctivo', NULL, '2026-11-03 21:07:00+00', NULL, 'Cambio de transmisor de caudal de solución por cortocircuito', 'simulado', 'bitacora', 6),
	(53, 1, NULL, 'correctivo', NULL, '2026-11-23 12:39:00+00', NULL, 'Reparación de cableado y borneras de la Pt100', 'simulado', 'bitacora', 4),
	(54, 1, NULL, 'correctivo', NULL, '2026-11-23 18:08:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1),
	(55, 1, NULL, 'correctivo', NULL, '2026-11-27 16:53:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(56, 1, NULL, 'correctivo', NULL, '2026-12-01 13:03:00+00', NULL, 'Reparación de caldera / resistencia de calefacción del betún', 'simulado', 'bitacora', 1),
	(58, 1, NULL, 'correctivo', NULL, '2026-12-22 16:32:00+00', NULL, 'Limpieza correctiva de filtro obstruido', 'simulado', 'bitacora', 7),
	(59, 1, NULL, 'correctivo', NULL, '2026-12-24 17:25:00+00', NULL, 'Limpieza química del intercambiador', 'simulado', 'bitacora', 11),
	(60, 1, NULL, 'correctivo', NULL, '2026-12-28 14:38:00+00', NULL, 'Limpieza de antena del radar por costra de asfalto', 'simulado', 'bitacora', 1);

--
-- Data for Name: tipos_falla; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.tipos_falla OVERRIDING SYSTEM VALUE VALUES
	(8, 'Anomalia_Desconocida', 'Comportamiento anómalo no clasificado', 'media', 'El molino se aleja de su comportamiento sano. Revisar los sensores señalados.', NULL),
	(3, 'Advertencia_Radar_Sucio_Betun', 'Radar del estanque de betún sucio', 'media', 'Programar limpieza de la antena del radar de TK-101.', 1),
	(1, 'Sobrecarga_Motor_Por_Asfalto_Frio', 'Sobrecarga del motor por asfalto frío', 'alta', 'Revisar caldera y calefacción de TK-101 antes de seguir cargando el molino.', 1),
	(5, 'Falla_Electrica_PT100_Betun', 'Falla eléctrica en Pt100 del betún', 'alta', 'Revisar alimentación de 24 V y borneras de la Pt100 de TK-101.', 4),
	(4, 'Cortocircuito_Transmisor_Caudal_Sol', 'Cortocircuito en transmisor de caudal de solución', 'alta', 'Revisar el lazo 4-20 mA de FT-201: la señal está saturada.', 6),
	(2, 'Filtro_Obstruido', 'Filtro obstruido', 'alta', 'Limpiar el filtro F-101: la presión diferencial supera el límite y cae el caudal.', 7),
	(7, 'Desgaste_Rodamientos_Molino', 'Desgaste de rodamientos del molino', 'alta', 'Programar cambio de rodamientos del molino MC-01.', 10),
	(6, 'Ensuciamiento_Intercambiador', 'Intercambiador sucio', 'media', 'Programar limpieza química del intercambiador E-301.', 11);

--
-- Data for Name: mantenimiento_fallas; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.mantenimiento_fallas VALUES
	(2, 2),
	(3, 3),
	(5, 5),
	(6, 1),
	(7, 2),
	(8, 3),
	(10, 3),
	(11, 2),
	(13, 1),
	(14, 2),
	(15, 3),
	(16, 6),
	(18, 4),
	(19, 3),
	(20, 2),
	(21, 6),
	(22, 5),
	(24, 4),
	(25, 1),
	(26, 2),
	(27, 3),
	(29, 5),
	(30, 4),
	(31, 2),
	(32, 3),
	(33, 7),
	(34, 6),
	(36, 2),
	(37, 3),
	(38, 4),
	(47, 2),
	(39, 6),
	(40, 2),
	(42, 3),
	(43, 2),
	(44, 7),
	(46, 1),
	(48, 3),
	(49, 6),
	(50, 1),
	(51, 4),
	(53, 5),
	(54, 3),
	(55, 2),
	(56, 1),
	(58, 2),
	(59, 6),
	(60, 3),
	(1, 2),
	(1, 3);
INSERT INTO mantpred.mantenimiento_fallas VALUES
	(1, 6),
	(1, 5),
	(4, 2),
	(4, 3),
	(4, 6),
	(4, 4),
	(4, 7),
	(9, 2),
	(9, 3),
	(9, 1),
	(9, 6),
	(9, 4),
	(9, 5),
	(12, 2),
	(12, 3),
	(12, 1),
	(12, 6),
	(12, 4),
	(12, 5),
	(17, 2),
	(17, 3),
	(17, 1),
	(17, 6),
	(17, 5),
	(17, 7),
	(23, 2),
	(23, 3),
	(23, 6),
	(23, 5),
	(28, 2),
	(28, 3),
	(28, 1),
	(28, 6),
	(35, 2),
	(35, 3),
	(35, 1),
	(35, 6),
	(35, 5),
	(41, 2),
	(41, 3),
	(41, 1),
	(41, 6),
	(41, 5),
	(45, 2),
	(45, 3),
	(45, 1),
	(45, 6),
	(45, 4),
	(45, 5),
	(52, 2);
INSERT INTO mantpred.mantenimiento_fallas VALUES
	(52, 3),
	(52, 6),
	(57, 2),
	(57, 3),
	(57, 6),
	(57, 4),
	(57, 5);

--
-- Data for Name: sensores; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.sensores OVERRIDING SYSTEM VALUE VALUES
	(20, 1, 'EST_niv_betum_dep', 'Estado NAMUR radar betún', 'estado', 'Radar TK-101', '0/1', NULL, NULL, 0.000, 0.000, 'digital', 'simulado', true, NULL, 1),
	(19, 1, 'AMP_eco_betum_dep', 'Eco radar betún', 'eco', 'Radar TK-101', 'dB', NULL, NULL, 25.000, 80.000, 'directa', 'simulado', true, NULL, 1),
	(18, 1, 'VOL_niv_betum_dep', 'Volumen estanque betún', 'volumen', 'Radar TK-101', 'L', 0.000, 30000.000, NULL, NULL, 'directa', 'simulado', true, NULL, 1),
	(17, 1, 'POR_niv_betum_dep', 'Nivel estanque betún', 'nivel', 'Radar TK-101', '%', 0.000, 100.000, 5.000, 95.000, 'directa', 'simulado', true, NULL, 1),
	(16, 1, 'DIS_niv_betum_dep', 'Distancia radar betún', 'distancia', 'Radar TK-101', 'm', 0.000, 15.000, NULL, NULL, 'directa', 'simulado', true, NULL, 1),
	(15, 1, 'VOLT_niv_betum_dep', 'Alimentación radar betún', 'voltaje', 'Radar TK-101', 'V', NULL, NULL, 23.000, 25.000, 'directa', 'simulado', true, NULL, 1),
	(14, 1, 'AMP_niv_betum_dep', 'Lazo radar betún', 'corriente_lazo', 'Radar TK-101', 'mA', 4.000, 20.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 1),
	(3, 1, 'T_ASFALTO', 'Temperatura de asfalto', 'temperatura', 'Termocupla tipo J', '°C', NULL, NULL, 130.000, 145.000, '4-20 mA', 'real', true, NULL, 1),
	(28, 1, 'AMP_eco_solucion_dep', 'Eco radar solución', 'eco', 'Radar TK-201', 'dB', NULL, NULL, 25.000, 85.000, 'directa', 'simulado', true, NULL, 2),
	(27, 1, 'POR_niv_solucion_dep', 'Nivel estanque solución', 'nivel', 'Radar TK-201', '%', 0.000, 100.000, 5.000, 90.000, 'directa', 'simulado', true, NULL, 2),
	(26, 1, 'DIS_niv_solucion_dep', 'Distancia radar solución', 'distancia', 'Radar TK-201', 'm', 0.000, 15.000, NULL, NULL, 'directa', 'simulado', true, NULL, 2),
	(23, 1, 'AMP_son_solucion_in', 'Lazo Pt100 solución', 'corriente_lazo', 'Transmisor TT-201', 'mA', 4.000, 20.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 2),
	(22, 1, 'RES_son_solucion_in', 'Resistencia Pt100 solución', 'resistencia', 'Pt100 TT-201', 'Ω', NULL, NULL, 107.000, 120.000, 'directa', 'simulado', true, NULL, 2),
	(21, 1, 'TEM_son_solucion_in', 'Temperatura solución', 'temperatura', 'Pt100 TT-201', '°C', 0.000, 100.000, 20.000, 50.000, '4-20 mA', 'simulado', true, NULL, 2),
	(5, 1, 'T_SOLUCION', 'Temperatura de solución', 'temperatura', 'Termocupla tipo J', '°C', NULL, NULL, 30.000, 40.000, '4-20 mA', 'real', true, NULL, 2),
	(35, 1, 'AMP_eco_emulsion_dep', 'Eco radar emulsión', 'eco', 'Radar TK-301', 'dB', NULL, NULL, 25.000, 80.000, 'directa', 'simulado', true, NULL, 3),
	(34, 1, 'DIS_niv_emulsion_dep', 'Distancia radar emulsión', 'distancia', 'Radar TK-301', 'm', 0.000, 15.000, NULL, NULL, 'directa', 'simulado', true, NULL, 3),
	(33, 1, 'AMP_niv_emulsion_dep', 'Lazo radar emulsión', 'corriente_lazo', 'Radar TK-301', 'mA', 4.000, 20.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 3),
	(32, 1, 'FRE_cau_emulsion_out', 'Frecuencia Coriolis emulsión', 'frecuencia', 'Coriolis emulsión', 'Hz', NULL, NULL, NULL, NULL, 'directa', 'simulado', true, NULL, 3),
	(31, 1, 'AMP_cau_emulsion_out', 'Lazo caudal emulsión', 'corriente_lazo', 'Coriolis emulsión', 'mA', 4.000, 20.000, 3.800, 20.500, '4-20 mA', 'simulado', true, NULL, 3),
	(30, 1, 'RES_son_emulsion_out', 'Resistencia Pt100 emulsión', 'resistencia', 'Pt100 TT-301', 'Ω', NULL, NULL, 113.000, 133.000, 'directa', 'simulado', true, NULL, 3),
	(29, 1, 'TEM_son_emulsion_out', 'Temperatura emulsión', 'temperatura', 'Pt100 TT-301', '°C', 0.000, 100.000, 35.000, 85.000, '4-20 mA', 'simulado', true, NULL, 3),
	(4, 1, 'T_EMULSION', 'Temperatura de emulsión', 'temperatura', 'Termocupla tipo J', '°C', NULL, NULL, 70.000, 80.000, '4-20 mA', 'real', true, NULL, 3),
	(10, 1, 'AMP_son_betum_in', 'Lazo Pt100 betún', 'corriente_lazo', 'Transmisor TT-101', 'mA', 4.000, 20.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 4),
	(9, 1, 'VOLT_son_betum_in', 'Alimentación Pt100 betún', 'voltaje', 'Transmisor TT-101', 'V', NULL, NULL, 23.000, 25.000, 'directa', 'simulado', true, NULL, 4),
	(8, 1, 'RES_son_betum_in', 'Resistencia Pt100 betún', 'resistencia', 'Pt100 TT-101', 'Ω', NULL, NULL, 150.000, 178.000, 'directa', 'simulado', true, NULL, 4),
	(7, 1, 'TEM_son_betum_in', 'Temperatura betún', 'temperatura', 'Pt100 TT-101', '°C', 0.000, 250.000, 130.000, 200.000, '4-20 mA', 'simulado', true, NULL, 4),
	(13, 1, 'VOLT_cau_betum_in', 'Alimentación Coriolis betún', 'voltaje', 'Coriolis FT-101', 'V', NULL, NULL, 23.000, 25.000, 'directa', 'simulado', true, NULL, 5),
	(12, 1, 'FRE_cau_betum_in', 'Frecuencia Coriolis betún', 'frecuencia', 'Coriolis FT-101', 'Hz', NULL, NULL, NULL, NULL, 'directa', 'simulado', true, NULL, 5),
	(11, 1, 'AMP_cau_betum_in', 'Lazo caudal betún', 'corriente_lazo', 'Coriolis FT-101', 'mA', 4.000, 20.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 5),
	(1, 1, 'ASFALTO', 'Caudal de asfalto', 'caudal', 'Caudalímetro Siemens', 'L/min', NULL, NULL, NULL, NULL, '4-20 mA', 'real', true, 'Observado ~299 L/min en producción', 5),
	(25, 1, 'FRE_cau_solucion_in', 'Frecuencia Coriolis solución', 'frecuencia', 'Coriolis FT-201', 'Hz', NULL, NULL, NULL, NULL, 'directa', 'simulado', true, NULL, 6),
	(24, 1, 'AMP_cau_solucion_in', 'Lazo caudal solución', 'corriente_lazo', 'Coriolis FT-201', 'mA', 4.000, 20.000, 3.800, 20.500, '4-20 mA', 'simulado', true, NULL, 6),
	(2, 1, 'SOLUCION', 'Caudal de solución', 'caudal', 'Caudalímetro Siemens', 'L/min', NULL, NULL, NULL, NULL, '4-20 mA', 'real', true, 'Observado ~225 L/min en producción', 6),
	(43, 1, 'PRE_dif_filtro_bar', 'Presión diferencial filtro', 'presion', 'Transmisor ΔP F-101', 'bar', 0.000, 3.000, 0.000, 1.000, '4-20 mA', 'simulado', true, NULL, 7),
	(42, 1, 'CAU_bomba_lpm', 'Caudal de la bomba', 'caudal', 'Bomba P-101', 'L/min', 0.000, 300.000, NULL, NULL, 'directa', 'simulado', true, NULL, 8),
	(45, 1, 'VAL_aire_linea', 'Línea de aire', 'posicion', 'Válvula de aire', '0/1', NULL, NULL, NULL, NULL, 'digital', 'simulado', true, NULL, 9),
	(44, 1, 'POS_valvula_3vias', 'Posición válvula 3 vías', 'posicion', 'Válvula V-101', '0/1', NULL, NULL, NULL, NULL, 'digital', 'simulado', true, NULL, 9),
	(46, 1, 'TEM_emulsion_molino_out', 'Temperatura salida molino', 'temperatura', 'Sensor salida MC-01', '°C', 0.000, 150.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 10),
	(41, 1, 'AMP_vib_motor_molino', 'Lazo vibración', 'corriente_lazo', 'Sensor de vibración', 'mA', 4.000, 20.000, NULL, NULL, '4-20 mA', 'simulado', true, NULL, 10),
	(40, 1, 'VIB_vel_motor_molino', 'Vibración del motor', 'vibracion', 'Sensor de vibración', 'mm/s', 0.000, 25.000, 0.000, 4.500, '4-20 mA', 'simulado', true, NULL, 10),
	(39, 1, 'TOR_vfd_motor_molino', 'Torque del motor', 'torque', 'Variador MC-01', '%', 0.000, 150.000, NULL, NULL, 'directa', 'simulado', true, NULL, 10),
	(38, 1, 'AMP_vfd_motor_molino', 'Corriente del motor', 'corriente', 'Variador MC-01', 'A', 0.000, 200.000, 0.000, 125.000, 'directa', 'simulado', true, NULL, 10),
	(37, 1, 'FRE_vfd_motor_molino', 'Frecuencia variador', 'frecuencia', 'Variador MC-01', 'Hz', 0.000, 60.000, NULL, NULL, 'directa', 'simulado', true, NULL, 10),
	(36, 1, 'RPM_motor_molino', 'Velocidad del motor', 'velocidad', 'Variador MC-01', 'RPM', 0.000, 3000.000, NULL, NULL, 'directa', 'simulado', true, NULL, 10),
	(47, 1, 'PRE_intercambiador_bar', 'Presión intercambiador', 'presion', 'Transmisor E-301', 'bar', 0.000, 6.000, 0.000, 3.600, '4-20 mA', 'simulado', true, NULL, 11),
	(6, 1, 'RT_PRESION', 'Presión de línea', 'presion', 'Transmisor de presión', 'bar', NULL, NULL, NULL, NULL, '4-20 mA', 'real', true, 'Ubicación exacta por confirmar con QLA', 11);

--
-- Data for Name: rangos_operacion; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(1, 7, 'detenida', 'convencional', 122.000, 161.000),
	(2, 8, 'detenida', 'convencional', 147.000, 162.000),
	(3, 9, 'detenida', 'convencional', 22.600, 24.000),
	(4, 10, 'detenida', 'convencional', 11.800, 14.300),
	(5, 11, 'detenida', 'convencional', 3.960, 4.040),
	(6, 12, 'detenida', 'convencional', 248.000, 252.000),
	(7, 14, 'detenida', 'convencional', 8.560, 19.200),
	(8, 16, 'detenida', 'convencional', 0.736, 10.700),
	(9, 17, 'detenida', 'convencional', 28.500, 95.100),
	(10, 18, 'detenida', 'convencional', 8551.000, 28529.000),
	(11, 19, 'detenida', 'convencional', 27.500, 65.800),
	(12, 21, 'detenida', 'convencional', 24.800, 34.700),
	(13, 22, 'detenida', 'convencional', 110.000, 113.000),
	(14, 23, 'detenida', 'convencional', 7.970, 9.550),
	(15, 24, 'detenida', 'convencional', 3.980, 5.330),
	(16, 25, 'detenida', 'convencional', 398.000, 402.000),
	(17, 26, 'detenida', 'convencional', 9.140, 12.100),
	(18, 27, 'detenida', 'convencional', 19.400, 39.000),
	(19, 28, 'detenida', 'convencional', 68.000, 72.000),
	(20, 29, 'detenida', 'convencional', 48.900, 74.800),
	(21, 30, 'detenida', 'convencional', 119.000, 129.000),
	(22, 31, 'detenida', 'convencional', 3.960, 4.040),
	(23, 32, 'detenida', 'convencional', 318.000, 322.000),
	(24, 33, 'detenida', 'convencional', 4.820, 13.300),
	(25, 34, 'detenida', 'convencional', 6.290, 14.200),
	(26, 35, 'detenida', 'convencional', 57.100, 62.900),
	(27, 36, 'detenida', 'convencional', -0.010, 0.010),
	(28, 37, 'detenida', 'convencional', -0.010, 0.010),
	(29, 38, 'detenida', 'convencional', -0.010, 0.010),
	(30, 39, 'detenida', 'convencional', -0.010, 0.010),
	(31, 40, 'detenida', 'convencional', 0.080, 0.150),
	(32, 41, 'detenida', 'convencional', 4.050, 4.090),
	(33, 42, 'detenida', 'convencional', -0.010, 0.010),
	(34, 43, 'detenida', 'convencional', 0.000, 0.022),
	(35, 46, 'detenida', 'convencional', 37.800, 40.500),
	(36, 47, 'detenida', 'convencional', -0.010, 0.010),
	(37, 7, 'detenida', 'ninguno', 124.000, 187.000),
	(38, 8, 'detenida', 'ninguno', 148.000, 172.000),
	(39, 9, 'detenida', 'ninguno', 22.600, 24.000),
	(40, 10, 'detenida', 'ninguno', 11.900, 15.900),
	(41, 11, 'detenida', 'ninguno', 3.960, 4.040),
	(42, 12, 'detenida', 'ninguno', 248.000, 252.000),
	(43, 14, 'detenida', 'ninguno', 7.940, 19.200),
	(44, 16, 'detenida', 'ninguno', 0.732, 11.300),
	(45, 17, 'detenida', 'ninguno', 24.600, 95.100),
	(46, 18, 'detenida', 'ninguno', 7381.000, 28536.000),
	(47, 19, 'detenida', 'ninguno', 26.400, 66.400),
	(48, 21, 'detenida', 'ninguno', 24.700, 33.000),
	(49, 22, 'detenida', 'ninguno', 110.000, 113.000),
	(50, 23, 'detenida', 'ninguno', 7.950, 9.280);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(51, 24, 'detenida', 'ninguno', 3.970, 5.330),
	(52, 25, 'detenida', 'ninguno', 398.000, 402.000),
	(53, 26, 'detenida', 'ninguno', 8.760, 11.900),
	(54, 27, 'detenida', 'ninguno', 20.900, 41.600),
	(55, 28, 'detenida', 'ninguno', 68.000, 72.000),
	(56, 29, 'detenida', 'ninguno', 50.100, 72.700),
	(57, 30, 'detenida', 'ninguno', 119.000, 128.000),
	(58, 31, 'detenida', 'ninguno', 3.960, 4.040),
	(59, 32, 'detenida', 'ninguno', 318.000, 322.000),
	(60, 33, 'detenida', 'ninguno', 5.130, 13.200),
	(61, 34, 'detenida', 'ninguno', 6.410, 13.900),
	(62, 35, 'detenida', 'ninguno', 57.000, 62.900),
	(63, 36, 'detenida', 'ninguno', -0.010, 0.010),
	(64, 37, 'detenida', 'ninguno', -0.010, 0.010),
	(65, 38, 'detenida', 'ninguno', -0.010, 0.010),
	(66, 39, 'detenida', 'ninguno', -0.010, 0.010),
	(67, 40, 'detenida', 'ninguno', 0.080, 0.150),
	(68, 41, 'detenida', 'ninguno', 4.050, 4.090),
	(69, 42, 'detenida', 'ninguno', -0.010, 0.010),
	(70, 43, 'detenida', 'ninguno', 0.000, 0.022),
	(71, 46, 'detenida', 'ninguno', 39.400, 40.600),
	(72, 47, 'detenida', 'ninguno', -0.010, 0.010),
	(73, 7, 'detenida', 'plastomerico', 137.000, 190.000),
	(74, 8, 'detenida', 'plastomerico', 153.000, 173.000),
	(75, 9, 'detenida', 'plastomerico', 22.800, 24.000),
	(76, 10, 'detenida', 'plastomerico', 12.800, 16.100),
	(77, 11, 'detenida', 'plastomerico', 3.960, 4.040),
	(78, 12, 'detenida', 'plastomerico', 245.000, 249.000),
	(79, 14, 'detenida', 'plastomerico', 8.690, 19.200),
	(80, 16, 'detenida', 'plastomerico', 0.735, 10.600),
	(81, 17, 'detenida', 'plastomerico', 29.300, 95.100),
	(82, 18, 'detenida', 'plastomerico', 8784.000, 28529.000),
	(83, 19, 'detenida', 'plastomerico', 27.600, 66.000),
	(84, 21, 'detenida', 'plastomerico', 25.100, 44.300),
	(85, 22, 'detenida', 'plastomerico', 110.000, 117.000),
	(86, 23, 'detenida', 'plastomerico', 8.020, 11.100),
	(87, 24, 'detenida', 'plastomerico', 3.970, 5.180),
	(88, 25, 'detenida', 'plastomerico', 398.000, 402.000),
	(89, 26, 'detenida', 'plastomerico', 8.580, 12.000),
	(90, 27, 'detenida', 'plastomerico', 20.300, 42.800),
	(91, 28, 'detenida', 'plastomerico', 68.000, 71.900),
	(92, 29, 'detenida', 'plastomerico', 51.300, 85.000),
	(93, 30, 'detenida', 'plastomerico', 120.000, 133.000),
	(94, 31, 'detenida', 'plastomerico', 3.960, 4.040),
	(95, 32, 'detenida', 'plastomerico', 318.000, 322.000),
	(96, 33, 'detenida', 'plastomerico', 4.770, 13.400),
	(97, 34, 'detenida', 'plastomerico', 6.160, 14.300),
	(98, 35, 'detenida', 'plastomerico', 57.000, 62.900),
	(99, 36, 'detenida', 'plastomerico', -0.010, 0.010),
	(100, 37, 'detenida', 'plastomerico', -0.010, 0.010);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(101, 38, 'detenida', 'plastomerico', -0.010, 0.010),
	(102, 39, 'detenida', 'plastomerico', -0.010, 0.010),
	(103, 40, 'detenida', 'plastomerico', 0.080, 0.150),
	(104, 41, 'detenida', 'plastomerico', 4.050, 4.090),
	(105, 42, 'detenida', 'plastomerico', -0.010, 0.010),
	(106, 43, 'detenida', 'plastomerico', 0.000, 0.022),
	(107, 46, 'detenida', 'plastomerico', 37.800, 40.500),
	(108, 47, 'detenida', 'plastomerico', -0.010, 0.010),
	(109, 7, 'espera', 'convencional', 121.000, 139.000),
	(110, 8, 'espera', 'convencional', 147.000, 154.000),
	(111, 9, 'espera', 'convencional', 22.600, 24.000),
	(112, 10, 'espera', 'convencional', 11.800, 12.900),
	(113, 11, 'espera', 'convencional', 3.960, 4.040),
	(114, 12, 'espera', 'convencional', 248.000, 252.000),
	(115, 14, 'espera', 'convencional', 8.920, 19.200),
	(116, 16, 'espera', 'convencional', 0.737, 10.400),
	(117, 17, 'espera', 'convencional', 30.700, 95.100),
	(118, 18, 'espera', 'convencional', 9218.000, 28526.000),
	(119, 19, 'espera', 'convencional', 27.300, 66.000),
	(120, 21, 'espera', 'convencional', 33.900, 35.600),
	(121, 22, 'espera', 'convencional', 113.000, 114.000),
	(122, 23, 'espera', 'convencional', 9.420, 9.690),
	(123, 24, 'espera', 'convencional', 3.970, 5.330),
	(124, 25, 'espera', 'convencional', 398.000, 402.000),
	(125, 26, 'espera', 'convencional', 3.680, 11.800),
	(126, 27, 'espera', 'convencional', 21.300, 75.500),
	(127, 28, 'espera', 'convencional', 68.000, 72.000),
	(128, 29, 'espera', 'convencional', 63.100, 74.200),
	(129, 30, 'espera', 'convencional', 124.000, 129.000),
	(130, 31, 'espera', 'convencional', 3.960, 4.040),
	(131, 32, 'espera', 'convencional', 318.000, 322.000),
	(132, 33, 'espera', 'convencional', 5.070, 14.300),
	(133, 34, 'espera', 'convencional', 5.320, 14.000),
	(134, 35, 'espera', 'convencional', 57.100, 63.000),
	(135, 36, 'espera', 'convencional', -0.010, 0.010),
	(136, 37, 'espera', 'convencional', -0.010, 0.010),
	(137, 38, 'espera', 'convencional', -0.010, 0.010),
	(138, 39, 'espera', 'convencional', -0.010, 0.010),
	(139, 40, 'espera', 'convencional', 0.080, 0.150),
	(140, 41, 'espera', 'convencional', 4.050, 4.090),
	(141, 42, 'espera', 'convencional', -0.010, 0.010),
	(142, 43, 'espera', 'convencional', 0.000, 0.023),
	(143, 46, 'espera', 'convencional', 35.300, 70.700),
	(144, 47, 'espera', 'convencional', -0.010, 0.010),
	(145, 7, 'espera', 'plastomerico', 171.000, 189.000),
	(146, 8, 'espera', 'plastomerico', 166.000, 173.000),
	(147, 9, 'espera', 'plastomerico', 22.800, 24.000),
	(148, 10, 'espera', 'plastomerico', 15.000, 16.100),
	(149, 11, 'espera', 'plastomerico', 3.960, 4.040),
	(150, 12, 'espera', 'plastomerico', 245.000, 249.000);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(151, 14, 'espera', 'plastomerico', 8.880, 19.200),
	(152, 16, 'espera', 'plastomerico', 0.738, 10.400),
	(153, 17, 'espera', 'plastomerico', 30.500, 95.100),
	(154, 18, 'espera', 'plastomerico', 9142.000, 28524.000),
	(155, 19, 'espera', 'plastomerico', 30.500, 65.900),
	(156, 21, 'espera', 'plastomerico', 42.400, 45.500),
	(157, 22, 'espera', 'plastomerico', 116.000, 118.000),
	(158, 23, 'espera', 'plastomerico', 10.800, 11.300),
	(159, 24, 'espera', 'plastomerico', 3.980, 5.240),
	(160, 25, 'espera', 'plastomerico', 398.000, 402.000),
	(161, 26, 'espera', 'plastomerico', 3.680, 11.100),
	(162, 27, 'espera', 'plastomerico', 26.200, 75.400),
	(163, 28, 'espera', 'plastomerico', 68.000, 71.900),
	(164, 29, 'espera', 'plastomerico', 63.100, 88.100),
	(165, 30, 'espera', 'plastomerico', 124.000, 134.000),
	(166, 31, 'espera', 'plastomerico', 3.960, 4.040),
	(167, 32, 'espera', 'plastomerico', 318.000, 322.000),
	(168, 33, 'espera', 'plastomerico', 4.930, 14.200),
	(169, 34, 'espera', 'plastomerico', 5.390, 14.100),
	(170, 35, 'espera', 'plastomerico', 57.000, 62.900),
	(171, 36, 'espera', 'plastomerico', -0.010, 0.010),
	(172, 37, 'espera', 'plastomerico', -0.010, 0.010),
	(173, 38, 'espera', 'plastomerico', -0.010, 0.010),
	(174, 39, 'espera', 'plastomerico', -0.010, 0.010),
	(175, 40, 'espera', 'plastomerico', 0.080, 0.150),
	(176, 41, 'espera', 'plastomerico', 4.050, 4.090),
	(177, 42, 'espera', 'plastomerico', -0.010, 0.010),
	(178, 43, 'espera', 'plastomerico', 0.000, 0.022),
	(179, 46, 'espera', 'plastomerico', 35.300, 88.900),
	(180, 47, 'espera', 'plastomerico', -0.010, 0.010),
	(181, 7, 'limpieza', 'convencional', 122.000, 138.000),
	(182, 8, 'limpieza', 'convencional', 147.000, 153.000),
	(183, 9, 'limpieza', 'convencional', 22.600, 24.000),
	(184, 10, 'limpieza', 'convencional', 11.800, 12.900),
	(185, 11, 'limpieza', 'convencional', 3.960, 4.040),
	(186, 12, 'limpieza', 'convencional', 248.000, 252.000),
	(187, 14, 'limpieza', 'convencional', 8.560, 16.600),
	(188, 16, 'limpieza', 'convencional', 3.230, 10.700),
	(189, 17, 'limpieza', 'convencional', 28.500, 78.500),
	(190, 18, 'limpieza', 'convencional', 8544.000, 23542.000),
	(191, 19, 'limpieza', 'convencional', 27.200, 65.800),
	(192, 21, 'limpieza', 'convencional', 34.400, 35.600),
	(193, 22, 'limpieza', 'convencional', 113.000, 114.000),
	(194, 23, 'limpieza', 'convencional', 9.510, 9.700),
	(195, 24, 'limpieza', 'convencional', 3.970, 5.270),
	(196, 25, 'limpieza', 'convencional', 398.000, 402.000),
	(197, 26, 'limpieza', 'convencional', 9.320, 12.100),
	(198, 27, 'limpieza', 'convencional', 19.400, 37.900),
	(199, 28, 'limpieza', 'convencional', 68.100, 72.100),
	(200, 29, 'limpieza', 'convencional', 69.500, 74.700);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(201, 30, 'limpieza', 'convencional', 127.000, 129.000),
	(202, 31, 'limpieza', 'convencional', 17.600, 18.100),
	(203, 32, 'limpieza', 'convencional', 323.000, 346.000),
	(204, 33, 'limpieza', 'convencional', 5.040, 17.800),
	(205, 34, 'limpieza', 'convencional', 2.050, 14.000),
	(206, 35, 'limpieza', 'convencional', 57.000, 63.000),
	(207, 36, 'limpieza', 'convencional', 2892.000, 2908.000),
	(208, 37, 'limpieza', 'convencional', 49.900, 50.100),
	(209, 38, 'limpieza', 'convencional', 55.500, 62.400),
	(210, 39, 'limpieza', 'convencional', 37.700, 42.000),
	(211, 40, 'limpieza', 'convencional', 1.860, 4.500),
	(212, 41, 'limpieza', 'convencional', 5.190, 7.390),
	(213, 42, 'limpieza', 'convencional', 255.000, 265.000),
	(214, 43, 'limpieza', 'convencional', 0.314, 1.100),
	(215, 46, 'limpieza', 'convencional', 34.500, 59.900),
	(216, 47, 'limpieza', 'convencional', -0.010, 0.010),
	(217, 7, 'limpieza', 'plastomerico', 174.000, 189.000),
	(218, 8, 'limpieza', 'plastomerico', 167.000, 173.000),
	(219, 9, 'limpieza', 'plastomerico', 22.800, 24.000),
	(220, 10, 'limpieza', 'plastomerico', 15.100, 16.100),
	(221, 11, 'limpieza', 'plastomerico', 3.960, 4.030),
	(222, 12, 'limpieza', 'plastomerico', 245.000, 249.000),
	(223, 14, 'limpieza', 'plastomerico', 8.620, 16.500),
	(224, 16, 'limpieza', 'plastomerico', 3.280, 10.700),
	(225, 17, 'limpieza', 'plastomerico', 28.900, 78.100),
	(226, 18, 'limpieza', 'plastomerico', 8662.000, 23431.000),
	(227, 19, 'limpieza', 'plastomerico', 30.000, 66.400),
	(228, 21, 'limpieza', 'plastomerico', 44.400, 45.600),
	(229, 22, 'limpieza', 'plastomerico', 117.000, 118.000),
	(230, 23, 'limpieza', 'plastomerico', 11.100, 11.300),
	(231, 24, 'limpieza', 'plastomerico', 3.980, 5.160),
	(232, 25, 'limpieza', 'plastomerico', 398.000, 402.000),
	(233, 26, 'limpieza', 'plastomerico', 8.760, 11.300),
	(234, 27, 'limpieza', 'plastomerico', 24.700, 41.600),
	(235, 28, 'limpieza', 'plastomerico', 68.000, 71.700),
	(236, 29, 'limpieza', 'plastomerico', 79.500, 89.600),
	(237, 30, 'limpieza', 'plastomerico', 131.000, 135.000),
	(238, 31, 'limpieza', 'plastomerico', 17.600, 18.100),
	(239, 32, 'limpieza', 'plastomerico', 323.000, 346.000),
	(240, 33, 'limpieza', 'plastomerico', 5.570, 17.700),
	(241, 34, 'limpieza', 'plastomerico', 2.190, 13.500),
	(242, 35, 'limpieza', 'plastomerico', 57.200, 63.100),
	(243, 36, 'limpieza', 'plastomerico', 2892.000, 2908.000),
	(244, 37, 'limpieza', 'plastomerico', 49.900, 50.100),
	(245, 38, 'limpieza', 'plastomerico', 55.800, 62.600),
	(246, 39, 'limpieza', 'plastomerico', 37.700, 42.000),
	(247, 40, 'limpieza', 'plastomerico', 1.850, 4.500),
	(248, 41, 'limpieza', 'plastomerico', 5.180, 8.000),
	(249, 42, 'limpieza', 'plastomerico', 255.000, 265.000),
	(250, 43, 'limpieza', 'plastomerico', 0.328, 1.100);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(251, 46, 'limpieza', 'plastomerico', 34.500, 73.300),
	(252, 47, 'limpieza', 'plastomerico', -0.010, 0.010),
	(253, 7, 'mantenimiento', 'ninguno', 120.000, 159.000),
	(254, 8, 'mantenimiento', 'ninguno', 146.000, 161.000),
	(255, 9, 'mantenimiento', 'ninguno', 22.600, 24.000),
	(256, 10, 'mantenimiento', 'ninguno', 11.700, 14.200),
	(257, 11, 'mantenimiento', 'ninguno', 3.960, 4.040),
	(258, 12, 'mantenimiento', 'ninguno', 248.000, 252.000),
	(259, 14, 'mantenimiento', 'ninguno', 10.600, 19.200),
	(260, 16, 'mantenimiento', 'ninguno', 0.732, 8.830),
	(261, 17, 'mantenimiento', 'ninguno', 41.100, 95.100),
	(262, 18, 'mantenimiento', 'ninguno', 12342.000, 28536.000),
	(263, 19, 'mantenimiento', 'ninguno', 31.400, 63.000),
	(264, 21, 'mantenimiento', 'ninguno', 29.600, 35.600),
	(265, 22, 'mantenimiento', 'ninguno', 111.000, 114.000),
	(266, 23, 'mantenimiento', 'ninguno', 8.740, 9.700),
	(267, 24, 'mantenimiento', 'ninguno', 3.970, 5.320),
	(268, 25, 'mantenimiento', 'ninguno', 398.000, 402.000),
	(269, 26, 'mantenimiento', 'ninguno', 9.060, 11.900),
	(270, 27, 'mantenimiento', 'ninguno', 20.500, 39.600),
	(271, 28, 'mantenimiento', 'ninguno', 68.000, 72.100),
	(272, 29, 'mantenimiento', 'ninguno', 58.900, 68.200),
	(273, 30, 'mantenimiento', 'ninguno', 123.000, 126.000),
	(274, 31, 'mantenimiento', 'ninguno', 3.960, 4.040),
	(275, 32, 'mantenimiento', 'ninguno', 318.000, 322.000),
	(276, 33, 'mantenimiento', 'ninguno', 6.300, 12.600),
	(277, 34, 'mantenimiento', 'ninguno', 6.970, 12.800),
	(278, 35, 'mantenimiento', 'ninguno', 56.900, 62.700),
	(279, 36, 'mantenimiento', 'ninguno', -0.010, 0.010),
	(280, 37, 'mantenimiento', 'ninguno', -0.010, 0.010),
	(281, 38, 'mantenimiento', 'ninguno', -0.010, 0.010),
	(282, 39, 'mantenimiento', 'ninguno', -0.010, 0.010),
	(283, 40, 'mantenimiento', 'ninguno', 0.080, 0.150),
	(284, 41, 'mantenimiento', 'ninguno', 4.050, 4.090),
	(285, 42, 'mantenimiento', 'ninguno', -0.010, 0.010),
	(286, 43, 'mantenimiento', 'ninguno', 0.000, 0.022),
	(287, 46, 'mantenimiento', 'ninguno', 39.400, 40.600),
	(288, 47, 'mantenimiento', 'ninguno', -0.010, 0.010),
	(289, 7, 'preparacion', 'convencional', 121.000, 143.000),
	(290, 8, 'preparacion', 'convencional', 147.000, 155.000),
	(291, 9, 'preparacion', 'convencional', 22.700, 24.000),
	(292, 10, 'preparacion', 'convencional', 11.700, 13.100),
	(293, 11, 'preparacion', 'convencional', 3.960, 4.040),
	(294, 12, 'preparacion', 'convencional', 248.000, 252.000),
	(295, 14, 'preparacion', 'convencional', 8.560, 19.200),
	(296, 16, 'preparacion', 'convencional', 0.736, 10.700),
	(297, 17, 'preparacion', 'convencional', 28.500, 95.100),
	(298, 18, 'preparacion', 'convencional', 8545.000, 28529.000),
	(299, 19, 'preparacion', 'convencional', 27.700, 65.900),
	(300, 21, 'preparacion', 'convencional', 26.800, 33.600);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(301, 22, 'preparacion', 'convencional', 110.000, 113.000),
	(302, 23, 'preparacion', 'convencional', 8.290, 9.380),
	(303, 24, 'preparacion', 'convencional', 3.980, 5.350),
	(304, 25, 'preparacion', 'convencional', 398.000, 402.000),
	(305, 26, 'preparacion', 'convencional', 3.600, 10.800),
	(306, 27, 'preparacion', 'convencional', 27.800, 76.000),
	(307, 28, 'preparacion', 'convencional', 68.000, 72.000),
	(308, 29, 'preparacion', 'convencional', 47.900, 73.300),
	(309, 30, 'preparacion', 'convencional', 118.000, 128.000),
	(310, 31, 'preparacion', 'convencional', 3.960, 4.040),
	(311, 32, 'preparacion', 'convencional', 318.000, 322.000),
	(312, 33, 'preparacion', 'convencional', 4.820, 13.400),
	(313, 34, 'preparacion', 'convencional', 6.170, 14.200),
	(314, 35, 'preparacion', 'convencional', 57.100, 62.800),
	(315, 36, 'preparacion', 'convencional', -0.010, 0.010),
	(316, 37, 'preparacion', 'convencional', -0.010, 0.010),
	(317, 38, 'preparacion', 'convencional', -0.010, 0.010),
	(318, 39, 'preparacion', 'convencional', -0.010, 0.010),
	(319, 40, 'preparacion', 'convencional', 0.080, 0.150),
	(320, 41, 'preparacion', 'convencional', 4.050, 4.090),
	(321, 42, 'preparacion', 'convencional', -0.010, 0.010),
	(322, 43, 'preparacion', 'convencional', 0.000, 0.022),
	(323, 46, 'preparacion', 'convencional', 39.400, 40.600),
	(324, 47, 'preparacion', 'convencional', -0.010, 0.010),
	(325, 7, 'preparacion', 'plastomerico', 167.000, 188.000),
	(326, 8, 'preparacion', 'plastomerico', 164.000, 172.000),
	(327, 9, 'preparacion', 'plastomerico', 22.900, 24.000),
	(328, 10, 'preparacion', 'plastomerico', 14.700, 16.000),
	(329, 11, 'preparacion', 'plastomerico', 3.960, 4.040),
	(330, 12, 'preparacion', 'plastomerico', 245.000, 249.000),
	(331, 14, 'preparacion', 'plastomerico', 8.710, 19.200),
	(332, 16, 'preparacion', 'plastomerico', 0.735, 10.600),
	(333, 17, 'preparacion', 'plastomerico', 29.500, 95.100),
	(334, 18, 'preparacion', 'plastomerico', 8837.000, 28530.000),
	(335, 19, 'preparacion', 'plastomerico', 31.200, 65.200),
	(336, 21, 'preparacion', 'plastomerico', 28.000, 41.300),
	(337, 22, 'preparacion', 'plastomerico', 111.000, 116.000),
	(338, 23, 'preparacion', 'plastomerico', 8.480, 10.600),
	(339, 24, 'preparacion', 'plastomerico', 3.970, 5.090),
	(340, 25, 'preparacion', 'plastomerico', 398.000, 402.000),
	(341, 26, 'preparacion', 'plastomerico', 3.590, 10.900),
	(342, 27, 'preparacion', 'plastomerico', 27.300, 76.100),
	(343, 28, 'preparacion', 'plastomerico', 68.000, 71.900),
	(344, 29, 'preparacion', 'plastomerico', 48.500, 72.500),
	(345, 30, 'preparacion', 'plastomerico', 119.000, 128.000),
	(346, 31, 'preparacion', 'plastomerico', 3.960, 4.040),
	(347, 32, 'preparacion', 'plastomerico', 318.000, 322.000),
	(348, 33, 'preparacion', 'plastomerico', 4.740, 13.400),
	(349, 34, 'preparacion', 'plastomerico', 6.200, 14.300),
	(350, 35, 'preparacion', 'plastomerico', 57.100, 63.200);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(351, 36, 'preparacion', 'plastomerico', -0.010, 0.010),
	(352, 37, 'preparacion', 'plastomerico', -0.010, 0.010),
	(353, 38, 'preparacion', 'plastomerico', -0.010, 0.010),
	(354, 39, 'preparacion', 'plastomerico', -0.010, 0.010),
	(355, 40, 'preparacion', 'plastomerico', 0.080, 0.150),
	(356, 41, 'preparacion', 'plastomerico', 4.050, 4.090),
	(357, 42, 'preparacion', 'plastomerico', -0.010, 0.010),
	(358, 43, 'preparacion', 'plastomerico', 0.000, 0.023),
	(359, 46, 'preparacion', 'plastomerico', 39.400, 40.600),
	(360, 47, 'preparacion', 'plastomerico', -0.010, 0.010),
	(361, 7, 'produccion', 'convencional', 126.000, 140.000),
	(362, 8, 'produccion', 'convencional', 148.000, 154.000),
	(363, 9, 'produccion', 'convencional', 22.600, 24.000),
	(364, 10, 'produccion', 'convencional', 12.000, 13.000),
	(365, 11, 'produccion', 'convencional', 11.900, 13.200),
	(366, 12, 'produccion', 'convencional', 248.000, 252.000),
	(367, 14, 'produccion', 'convencional', 8.910, 18.600),
	(368, 16, 'produccion', 'convencional', 1.290, 10.400),
	(369, 17, 'produccion', 'convencional', 30.700, 91.400),
	(370, 18, 'produccion', 'convencional', 9201.000, 27417.000),
	(371, 19, 'produccion', 'convencional', 27.800, 65.800),
	(372, 21, 'produccion', 'convencional', 33.800, 35.500),
	(373, 22, 'produccion', 'convencional', 113.000, 114.000),
	(374, 23, 'produccion', 'convencional', 9.410, 9.680),
	(375, 24, 'produccion', 'convencional', 12.300, 14.400),
	(376, 25, 'produccion', 'convencional', 398.000, 402.000),
	(377, 26, 'produccion', 'convencional', 3.880, 11.100),
	(378, 27, 'produccion', 'convencional', 25.800, 74.200),
	(379, 28, 'produccion', 'convencional', 68.000, 72.000),
	(380, 29, 'produccion', 'convencional', 61.100, 74.600),
	(381, 30, 'produccion', 'convencional', 124.000, 129.000),
	(382, 31, 'produccion', 'convencional', 12.500, 13.800),
	(383, 32, 'produccion', 'convencional', 318.000, 322.000),
	(384, 33, 'produccion', 'convencional', 5.960, 16.700),
	(385, 34, 'produccion', 'convencional', 3.090, 13.200),
	(386, 35, 'produccion', 'convencional', 57.100, 62.900),
	(387, 36, 'produccion', 'convencional', 2891.000, 2907.000),
	(388, 37, 'produccion', 'convencional', 49.800, 50.100),
	(389, 38, 'produccion', 'convencional', 103.000, 110.000),
	(390, 39, 'produccion', 'convencional', 69.600, 74.300),
	(391, 40, 'produccion', 'convencional', 1.880, 4.500),
	(392, 41, 'produccion', 'convencional', 5.200, 7.330),
	(393, 42, 'produccion', 'convencional', 159.000, 184.000),
	(394, 43, 'produccion', 'convencional', 0.253, 0.917),
	(395, 46, 'produccion', 'convencional', 60.600, 75.300),
	(396, 47, 'produccion', 'convencional', -0.010, 0.010),
	(397, 7, 'produccion', 'plastomerico', 177.000, 190.000),
	(398, 8, 'produccion', 'plastomerico', 168.000, 173.000),
	(399, 9, 'produccion', 'plastomerico', 22.800, 24.000),
	(400, 10, 'produccion', 'plastomerico', 15.300, 16.100);
INSERT INTO mantpred.rangos_operacion OVERRIDING SYSTEM VALUE VALUES
	(401, 11, 'produccion', 'plastomerico', 12.300, 13.600),
	(402, 12, 'produccion', 'plastomerico', 245.000, 249.000),
	(403, 14, 'produccion', 'plastomerico', 8.870, 18.500),
	(404, 16, 'produccion', 'plastomerico', 1.360, 10.400),
	(405, 17, 'produccion', 'plastomerico', 30.500, 90.900),
	(406, 18, 'produccion', 'plastomerico', 9138.000, 27280.000),
	(407, 19, 'produccion', 'plastomerico', 29.200, 65.600),
	(408, 21, 'produccion', 'plastomerico', 42.600, 45.500),
	(409, 22, 'produccion', 'plastomerico', 116.000, 117.000),
	(410, 23, 'produccion', 'plastomerico', 10.800, 11.300),
	(411, 24, 'produccion', 'plastomerico', 11.700, 13.600),
	(412, 25, 'produccion', 'plastomerico', 398.000, 402.000),
	(413, 26, 'produccion', 'plastomerico', 3.860, 10.600),
	(414, 27, 'produccion', 'plastomerico', 29.600, 74.200),
	(415, 28, 'produccion', 'plastomerico', 68.000, 71.900),
	(416, 29, 'produccion', 'plastomerico', 66.100, 87.600),
	(417, 30, 'produccion', 'plastomerico', 125.000, 134.000),
	(418, 31, 'produccion', 'plastomerico', 12.500, 13.800),
	(419, 32, 'produccion', 'plastomerico', 318.000, 322.000),
	(420, 33, 'produccion', 'plastomerico', 5.750, 16.400),
	(421, 34, 'produccion', 'plastomerico', 3.410, 13.400),
	(422, 35, 'produccion', 'plastomerico', 56.900, 62.900),
	(423, 36, 'produccion', 'plastomerico', 2882.000, 2898.000),
	(424, 37, 'produccion', 'plastomerico', 49.700, 50.000),
	(425, 38, 'produccion', 'plastomerico', 114.000, 121.000),
	(426, 39, 'produccion', 'plastomerico', 77.100, 82.100),
	(427, 40, 'produccion', 'plastomerico', 1.900, 4.500),
	(428, 41, 'produccion', 'plastomerico', 5.220, 7.640),
	(429, 42, 'produccion', 'plastomerico', 159.000, 184.000),
	(430, 43, 'produccion', 'plastomerico', 0.256, 0.926),
	(431, 46, 'produccion', 'plastomerico', 73.000, 95.500),
	(432, 47, 'produccion', 'plastomerico', 2.450, 3.620);

--
-- Data for Name: reglas_alarma; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.reglas_alarma OVERRIDING SYSTEM VALUE VALUES
	(1, 'BETUN_FRIO_PLASTO', 7, '<', 175.000, 'plastomerico', true, 'media', 'Temperatura del betún bajo 175 °C (plastomérico)', 'Revisar caldera y calefacción de TK-101.', true),
	(2, 'BETUN_FRIO_CONV', 7, '<', 125.000, 'convencional', true, 'media', 'Temperatura del betún bajo 125 °C (convencional)', 'Revisar caldera y calefacción de TK-101.', true),
	(3, 'PT100_SIN_ALIMENTACION', 9, '<', 20.000, NULL, false, 'alta', 'Alimentación de la Pt100 del betún bajo 20 V', 'Revisar fuente de 24 V y borneras de la Pt100 de TK-101.', true),
	(4, 'LAZO_CAUDAL_SOL_ALTO', 24, '>', 21.000, NULL, false, 'alta', 'Lazo del caudalímetro de solución sobre 21 mA', 'Revisar el lazo 4-20 mA de FT-201 (posible cortocircuito).', true),
	(5, 'LAZO_CAUDAL_EMU_BAJO', 31, '<', 3.600, NULL, false, 'alta', 'Lazo del caudal de emulsión bajo 3,6 mA', 'Revisar el lazo 4-20 mA del caudalímetro de emulsión (posible corte).', true),
	(6, 'CORRIENTE_ALTA', 38, '>', 130.000, NULL, true, 'alta', 'Corriente del motor sobre 130 A', 'Reducir carga y revisar temperatura del betún.', true),
	(7, 'VIBRACION_ALTA', 40, '>', 4.500, NULL, true, 'alta', 'Vibración del molino sobre 4,5 mm/s', 'Revisar rodamientos y alineación del molino MC-01.', true),
	(8, 'DP_FILTRO_ALTA', 43, '>', 1.100, NULL, true, 'media', 'ΔP del filtro sobre 1,1 bar', 'Programar limpieza del filtro F-101.', true);

--
-- Data for Name: roles; Type: TABLE DATA; Schema: mantpred; Owner: -
--

INSERT INTO mantpred.roles OVERRIDING SYSTEM VALUE VALUES
	(3, 'operador', 2, 'Ve todo el sistema: proceso, predicción, alarmas, salud, mantenimiento y simulación'),
	(1, 'administrador', 4, 'Todo lo del operador, más la gestión de usuarios y roles');

--
-- Name: componentes_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.componentes_id_seq', 11, true);

--
-- Name: equipos_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.equipos_id_seq', 1, true);

--
-- Name: mantenimientos_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.mantenimientos_id_seq', 60, true);

--
-- Name: rangos_operacion_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.rangos_operacion_id_seq', 432, true);

--
-- Name: reglas_alarma_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.reglas_alarma_id_seq', 8, true);

--
-- Name: roles_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.roles_id_seq', 4, true);

--
-- Name: sensores_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.sensores_id_seq', 47, true);

--
-- Name: tipos_falla_id_seq; Type: SEQUENCE SET; Schema: mantpred; Owner: -
--

SELECT pg_catalog.setval('mantpred.tipos_falla_id_seq', 8, true);

--
--

COMMIT;
