-- =====================================================================
-- Proyecto : Mantenimiento predictivo inteligente – Química Latinoamericana S.A.
-- Archivo  : migracion_v3.sql
-- Aplica   : sobre el esquema mantpred versión 2 (bd_mantenimiento_predictivo_v2.sql)
--
-- Qué cambia y por qué (historias de usuario del dashboard):
--  1. Roles: quedan solo 'operador' y 'administrador' (decisión del equipo).
--     Los usuarios con rol supervisor o visualizador pasan a operador.
--  2. rangos_operacion: banda normal de cada sensor según el modo de operación
--     (HU-02, HU-03, HU-04: "banda normal del modo de operación actual").
--  3. reglas_alarma: reglas fijas de instrumento y de proceso (HU-11).
--  4. predicciones: guarda método, umbral, alerta, días estimados, error del
--     autoencoder y detalle (sensores que más aportan) (HU-05, HU-07, HU-12).
--     Una fila por minuto para diagnóstico/vigilancia y una por hora para predicción.
--  5. condiciones_minuto: qué condición anómala hubo en cada minuto. Con ella una
--     alarma se activa si aparece en 3 de los últimos 5 minutos (HU-09).
--  6. alarmas: enlace a la regla que la originó y una sola alarma activa por causa.
--  7. mantenimientos: la bitácora llega desde la planta (solo lectura): se carga
--     la bitácora del año simulado (HU-13, HU-16).
--  8. purgar_datos_simulados(dias): borra lo simulado antiguo de todas las tablas
--     de series de tiempo (plan gratis de Supabase: 500 MB).
--
-- Cómo ejecutarlo en Supabase: SQL Editor -> pegar todo -> Run (una sola vez).
-- No borra lecturas ni usuarios existentes. Si algo falla, no se aplica nada (BEGIN/COMMIT).
-- =====================================================================

BEGIN;
SET search_path TO mantpred, extensions;

-- =====================================================================
-- 1. ROLES: operador y administrador
-- =====================================================================
UPDATE usuarios SET rol_id = (SELECT id FROM roles WHERE nombre = 'operador')
WHERE rol_id IN (SELECT id FROM roles WHERE nombre IN ('supervisor', 'visualizador'));

DELETE FROM roles WHERE nombre IN ('supervisor', 'visualizador');

DO $$
DECLARE c TEXT;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'mantpred.roles'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%nombre%' LOOP
        EXECUTE format('ALTER TABLE mantpred.roles DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
ALTER TABLE roles ADD CONSTRAINT roles_nombre_check CHECK (nombre IN ('administrador', 'operador'));

UPDATE roles SET descripcion = 'Ve todo el sistema: proceso, predicción, alarmas, salud, mantenimiento y simulación'
WHERE nombre = 'operador';
UPDATE roles SET descripcion = 'Todo lo del operador, más la gestión de usuarios y roles'
WHERE nombre = 'administrador';

-- =====================================================================
-- 2. BANDA NORMAL POR MODO DE OPERACIÓN
-- =====================================================================
CREATE TABLE rangos_operacion (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id     INTEGER       NOT NULL REFERENCES sensores (id),
    estado        VARCHAR(15)   NOT NULL
                  CHECK (estado IN ('detenida', 'preparacion', 'produccion', 'espera',
                                    'limpieza', 'mantenimiento')),
    tipo_asfalto  VARCHAR(15)   NOT NULL
                  CHECK (tipo_asfalto IN ('convencional', 'plastomerico', 'ninguno')),
    normal_min    NUMERIC(12,3) NOT NULL,
    normal_max    NUMERIC(12,3) NOT NULL,
    CHECK (normal_min <= normal_max),
    UNIQUE (sensor_id, estado, tipo_asfalto)
);

-- Se carga por tag y se traduce a sensor_id al final
CREATE TEMP TABLE rangos_tmp (tag TEXT, estado TEXT, tipo_asfalto TEXT, normal_min NUMERIC, normal_max NUMERIC)
    ON COMMIT DROP;

-- Bandas normales por modo: percentiles 2,5 y 97,5 de los minutos etiquetados 'Normal'
-- del Dataset_Molino_QLA_Realista (año completo), acotadas por los límites de las reglas fijas.
INSERT INTO rangos_tmp (tag, estado, tipo_asfalto, normal_min, normal_max) VALUES
 ('TEM_son_betum_in','detenida','convencional',122.0,161.0),
 ('RES_son_betum_in','detenida','convencional',147.0,162.0),
 ('VOLT_son_betum_in','detenida','convencional',22.6,24.0),
 ('AMP_son_betum_in','detenida','convencional',11.8,14.3),
 ('AMP_cau_betum_in','detenida','convencional',3.96,4.04),
 ('FRE_cau_betum_in','detenida','convencional',248.0,252.0),
 ('AMP_niv_betum_dep','detenida','convencional',8.56,19.2),
 ('DIS_niv_betum_dep','detenida','convencional',0.736,10.7),
 ('POR_niv_betum_dep','detenida','convencional',28.5,95.1),
 ('VOL_niv_betum_dep','detenida','convencional',8551.0,28529.0),
 ('AMP_eco_betum_dep','detenida','convencional',27.5,65.8),
 ('TEM_son_solucion_in','detenida','convencional',24.8,34.7),
 ('RES_son_solucion_in','detenida','convencional',110.0,113.0),
 ('AMP_son_solucion_in','detenida','convencional',7.97,9.55),
 ('AMP_cau_solucion_in','detenida','convencional',3.98,5.33),
 ('FRE_cau_solucion_in','detenida','convencional',398.0,402.0),
 ('DIS_niv_solucion_dep','detenida','convencional',9.14,12.1),
 ('POR_niv_solucion_dep','detenida','convencional',19.4,39.0),
 ('AMP_eco_solucion_dep','detenida','convencional',68.0,72.0),
 ('TEM_son_emulsion_out','detenida','convencional',48.9,74.8),
 ('RES_son_emulsion_out','detenida','convencional',119.0,129.0),
 ('AMP_cau_emulsion_out','detenida','convencional',3.96,4.04),
 ('FRE_cau_emulsion_out','detenida','convencional',318.0,322.0),
 ('AMP_niv_emulsion_dep','detenida','convencional',4.82,13.3),
 ('DIS_niv_emulsion_dep','detenida','convencional',6.29,14.2),
 ('AMP_eco_emulsion_dep','detenida','convencional',57.1,62.9),
 ('RPM_motor_molino','detenida','convencional',-0.01,0.01),
 ('FRE_vfd_motor_molino','detenida','convencional',-0.01,0.01),
 ('AMP_vfd_motor_molino','detenida','convencional',-0.01,0.01),
 ('TOR_vfd_motor_molino','detenida','convencional',-0.01,0.01),
 ('VIB_vel_motor_molino','detenida','convencional',0.08,0.15),
 ('AMP_vib_motor_molino','detenida','convencional',4.05,4.09),
 ('CAU_bomba_lpm','detenida','convencional',-0.01,0.01),
 ('PRE_dif_filtro_bar','detenida','convencional',0.0,0.022),
 ('TEM_emulsion_molino_out','detenida','convencional',37.8,40.5),
 ('PRE_intercambiador_bar','detenida','convencional',-0.01,0.01),
 ('TEM_son_betum_in','detenida','ninguno',124.0,187.0),
 ('RES_son_betum_in','detenida','ninguno',148.0,172.0),
 ('VOLT_son_betum_in','detenida','ninguno',22.6,24.0),
 ('AMP_son_betum_in','detenida','ninguno',11.9,15.9),
 ('AMP_cau_betum_in','detenida','ninguno',3.96,4.04),
 ('FRE_cau_betum_in','detenida','ninguno',248.0,252.0),
 ('AMP_niv_betum_dep','detenida','ninguno',7.94,19.2),
 ('DIS_niv_betum_dep','detenida','ninguno',0.732,11.3),
 ('POR_niv_betum_dep','detenida','ninguno',24.6,95.1),
 ('VOL_niv_betum_dep','detenida','ninguno',7381.0,28536.0),
 ('AMP_eco_betum_dep','detenida','ninguno',26.4,66.4),
 ('TEM_son_solucion_in','detenida','ninguno',24.7,33.0),
 ('RES_son_solucion_in','detenida','ninguno',110.0,113.0),
 ('AMP_son_solucion_in','detenida','ninguno',7.95,9.28),
 ('AMP_cau_solucion_in','detenida','ninguno',3.97,5.33),
 ('FRE_cau_solucion_in','detenida','ninguno',398.0,402.0),
 ('DIS_niv_solucion_dep','detenida','ninguno',8.76,11.9),
 ('POR_niv_solucion_dep','detenida','ninguno',20.9,41.6),
 ('AMP_eco_solucion_dep','detenida','ninguno',68.0,72.0),
 ('TEM_son_emulsion_out','detenida','ninguno',50.1,72.7),
 ('RES_son_emulsion_out','detenida','ninguno',119.0,128.0),
 ('AMP_cau_emulsion_out','detenida','ninguno',3.96,4.04),
 ('FRE_cau_emulsion_out','detenida','ninguno',318.0,322.0),
 ('AMP_niv_emulsion_dep','detenida','ninguno',5.13,13.2),
 ('DIS_niv_emulsion_dep','detenida','ninguno',6.41,13.9),
 ('AMP_eco_emulsion_dep','detenida','ninguno',57.0,62.9),
 ('RPM_motor_molino','detenida','ninguno',-0.01,0.01),
 ('FRE_vfd_motor_molino','detenida','ninguno',-0.01,0.01),
 ('AMP_vfd_motor_molino','detenida','ninguno',-0.01,0.01),
 ('TOR_vfd_motor_molino','detenida','ninguno',-0.01,0.01),
 ('VIB_vel_motor_molino','detenida','ninguno',0.08,0.15),
 ('AMP_vib_motor_molino','detenida','ninguno',4.05,4.09),
 ('CAU_bomba_lpm','detenida','ninguno',-0.01,0.01),
 ('PRE_dif_filtro_bar','detenida','ninguno',0.0,0.022),
 ('TEM_emulsion_molino_out','detenida','ninguno',39.4,40.6),
 ('PRE_intercambiador_bar','detenida','ninguno',-0.01,0.01),
 ('TEM_son_betum_in','detenida','plastomerico',137.0,190.0),
 ('RES_son_betum_in','detenida','plastomerico',153.0,173.0),
 ('VOLT_son_betum_in','detenida','plastomerico',22.8,24.0),
 ('AMP_son_betum_in','detenida','plastomerico',12.8,16.1),
 ('AMP_cau_betum_in','detenida','plastomerico',3.96,4.04),
 ('FRE_cau_betum_in','detenida','plastomerico',245.0,249.0),
 ('AMP_niv_betum_dep','detenida','plastomerico',8.69,19.2),
 ('DIS_niv_betum_dep','detenida','plastomerico',0.735,10.6),
 ('POR_niv_betum_dep','detenida','plastomerico',29.3,95.1),
 ('VOL_niv_betum_dep','detenida','plastomerico',8784.0,28529.0),
 ('AMP_eco_betum_dep','detenida','plastomerico',27.6,66.0),
 ('TEM_son_solucion_in','detenida','plastomerico',25.1,44.3),
 ('RES_son_solucion_in','detenida','plastomerico',110.0,117.0),
 ('AMP_son_solucion_in','detenida','plastomerico',8.02,11.1),
 ('AMP_cau_solucion_in','detenida','plastomerico',3.97,5.18),
 ('FRE_cau_solucion_in','detenida','plastomerico',398.0,402.0),
 ('DIS_niv_solucion_dep','detenida','plastomerico',8.58,12.0),
 ('POR_niv_solucion_dep','detenida','plastomerico',20.3,42.8),
 ('AMP_eco_solucion_dep','detenida','plastomerico',68.0,71.9),
 ('TEM_son_emulsion_out','detenida','plastomerico',51.3,85.0),
 ('RES_son_emulsion_out','detenida','plastomerico',120.0,133.0),
 ('AMP_cau_emulsion_out','detenida','plastomerico',3.96,4.04),
 ('FRE_cau_emulsion_out','detenida','plastomerico',318.0,322.0),
 ('AMP_niv_emulsion_dep','detenida','plastomerico',4.77,13.4),
 ('DIS_niv_emulsion_dep','detenida','plastomerico',6.16,14.3),
 ('AMP_eco_emulsion_dep','detenida','plastomerico',57.0,62.9),
 ('RPM_motor_molino','detenida','plastomerico',-0.01,0.01),
 ('FRE_vfd_motor_molino','detenida','plastomerico',-0.01,0.01),
 ('AMP_vfd_motor_molino','detenida','plastomerico',-0.01,0.01),
 ('TOR_vfd_motor_molino','detenida','plastomerico',-0.01,0.01),
 ('VIB_vel_motor_molino','detenida','plastomerico',0.08,0.15),
 ('AMP_vib_motor_molino','detenida','plastomerico',4.05,4.09),
 ('CAU_bomba_lpm','detenida','plastomerico',-0.01,0.01),
 ('PRE_dif_filtro_bar','detenida','plastomerico',0.0,0.022),
 ('TEM_emulsion_molino_out','detenida','plastomerico',37.8,40.5),
 ('PRE_intercambiador_bar','detenida','plastomerico',-0.01,0.01),
 ('TEM_son_betum_in','espera','convencional',121.0,139.0),
 ('RES_son_betum_in','espera','convencional',147.0,154.0),
 ('VOLT_son_betum_in','espera','convencional',22.6,24.0),
 ('AMP_son_betum_in','espera','convencional',11.8,12.9),
 ('AMP_cau_betum_in','espera','convencional',3.96,4.04),
 ('FRE_cau_betum_in','espera','convencional',248.0,252.0),
 ('AMP_niv_betum_dep','espera','convencional',8.92,19.2),
 ('DIS_niv_betum_dep','espera','convencional',0.737,10.4),
 ('POR_niv_betum_dep','espera','convencional',30.7,95.1),
 ('VOL_niv_betum_dep','espera','convencional',9218.0,28526.0),
 ('AMP_eco_betum_dep','espera','convencional',27.3,66.0),
 ('TEM_son_solucion_in','espera','convencional',33.9,35.6),
 ('RES_son_solucion_in','espera','convencional',113.0,114.0),
 ('AMP_son_solucion_in','espera','convencional',9.42,9.69),
 ('AMP_cau_solucion_in','espera','convencional',3.97,5.33),
 ('FRE_cau_solucion_in','espera','convencional',398.0,402.0),
 ('DIS_niv_solucion_dep','espera','convencional',3.68,11.8),
 ('POR_niv_solucion_dep','espera','convencional',21.3,75.5),
 ('AMP_eco_solucion_dep','espera','convencional',68.0,72.0),
 ('TEM_son_emulsion_out','espera','convencional',63.1,74.2),
 ('RES_son_emulsion_out','espera','convencional',124.0,129.0),
 ('AMP_cau_emulsion_out','espera','convencional',3.96,4.04),
 ('FRE_cau_emulsion_out','espera','convencional',318.0,322.0),
 ('AMP_niv_emulsion_dep','espera','convencional',5.07,14.3),
 ('DIS_niv_emulsion_dep','espera','convencional',5.32,14.0),
 ('AMP_eco_emulsion_dep','espera','convencional',57.1,63.0),
 ('RPM_motor_molino','espera','convencional',-0.01,0.01),
 ('FRE_vfd_motor_molino','espera','convencional',-0.01,0.01),
 ('AMP_vfd_motor_molino','espera','convencional',-0.01,0.01),
 ('TOR_vfd_motor_molino','espera','convencional',-0.01,0.01),
 ('VIB_vel_motor_molino','espera','convencional',0.08,0.15),
 ('AMP_vib_motor_molino','espera','convencional',4.05,4.09),
 ('CAU_bomba_lpm','espera','convencional',-0.01,0.01),
 ('PRE_dif_filtro_bar','espera','convencional',0.0,0.023),
 ('TEM_emulsion_molino_out','espera','convencional',35.3,70.7),
 ('PRE_intercambiador_bar','espera','convencional',-0.01,0.01),
 ('TEM_son_betum_in','espera','plastomerico',171.0,189.0),
 ('RES_son_betum_in','espera','plastomerico',166.0,173.0),
 ('VOLT_son_betum_in','espera','plastomerico',22.8,24.0),
 ('AMP_son_betum_in','espera','plastomerico',15.0,16.1),
 ('AMP_cau_betum_in','espera','plastomerico',3.96,4.04),
 ('FRE_cau_betum_in','espera','plastomerico',245.0,249.0),
 ('AMP_niv_betum_dep','espera','plastomerico',8.88,19.2),
 ('DIS_niv_betum_dep','espera','plastomerico',0.738,10.4),
 ('POR_niv_betum_dep','espera','plastomerico',30.5,95.1),
 ('VOL_niv_betum_dep','espera','plastomerico',9142.0,28524.0),
 ('AMP_eco_betum_dep','espera','plastomerico',30.5,65.9),
 ('TEM_son_solucion_in','espera','plastomerico',42.4,45.5),
 ('RES_son_solucion_in','espera','plastomerico',116.0,118.0),
 ('AMP_son_solucion_in','espera','plastomerico',10.8,11.3),
 ('AMP_cau_solucion_in','espera','plastomerico',3.98,5.24),
 ('FRE_cau_solucion_in','espera','plastomerico',398.0,402.0),
 ('DIS_niv_solucion_dep','espera','plastomerico',3.68,11.1),
 ('POR_niv_solucion_dep','espera','plastomerico',26.2,75.4),
 ('AMP_eco_solucion_dep','espera','plastomerico',68.0,71.9),
 ('TEM_son_emulsion_out','espera','plastomerico',63.1,88.1),
 ('RES_son_emulsion_out','espera','plastomerico',124.0,134.0),
 ('AMP_cau_emulsion_out','espera','plastomerico',3.96,4.04),
 ('FRE_cau_emulsion_out','espera','plastomerico',318.0,322.0),
 ('AMP_niv_emulsion_dep','espera','plastomerico',4.93,14.2),
 ('DIS_niv_emulsion_dep','espera','plastomerico',5.39,14.1),
 ('AMP_eco_emulsion_dep','espera','plastomerico',57.0,62.9),
 ('RPM_motor_molino','espera','plastomerico',-0.01,0.01),
 ('FRE_vfd_motor_molino','espera','plastomerico',-0.01,0.01),
 ('AMP_vfd_motor_molino','espera','plastomerico',-0.01,0.01),
 ('TOR_vfd_motor_molino','espera','plastomerico',-0.01,0.01),
 ('VIB_vel_motor_molino','espera','plastomerico',0.08,0.15),
 ('AMP_vib_motor_molino','espera','plastomerico',4.05,4.09),
 ('CAU_bomba_lpm','espera','plastomerico',-0.01,0.01),
 ('PRE_dif_filtro_bar','espera','plastomerico',0.0,0.022),
 ('TEM_emulsion_molino_out','espera','plastomerico',35.3,88.9),
 ('PRE_intercambiador_bar','espera','plastomerico',-0.01,0.01),
 ('TEM_son_betum_in','limpieza','convencional',122.0,138.0),
 ('RES_son_betum_in','limpieza','convencional',147.0,153.0),
 ('VOLT_son_betum_in','limpieza','convencional',22.6,24.0),
 ('AMP_son_betum_in','limpieza','convencional',11.8,12.9),
 ('AMP_cau_betum_in','limpieza','convencional',3.96,4.04),
 ('FRE_cau_betum_in','limpieza','convencional',248.0,252.0),
 ('AMP_niv_betum_dep','limpieza','convencional',8.56,16.6),
 ('DIS_niv_betum_dep','limpieza','convencional',3.23,10.7),
 ('POR_niv_betum_dep','limpieza','convencional',28.5,78.5),
 ('VOL_niv_betum_dep','limpieza','convencional',8544.0,23542.0),
 ('AMP_eco_betum_dep','limpieza','convencional',27.2,65.8),
 ('TEM_son_solucion_in','limpieza','convencional',34.4,35.6),
 ('RES_son_solucion_in','limpieza','convencional',113.0,114.0),
 ('AMP_son_solucion_in','limpieza','convencional',9.51,9.7),
 ('AMP_cau_solucion_in','limpieza','convencional',3.97,5.27),
 ('FRE_cau_solucion_in','limpieza','convencional',398.0,402.0),
 ('DIS_niv_solucion_dep','limpieza','convencional',9.32,12.1),
 ('POR_niv_solucion_dep','limpieza','convencional',19.4,37.9),
 ('AMP_eco_solucion_dep','limpieza','convencional',68.1,72.1),
 ('TEM_son_emulsion_out','limpieza','convencional',69.5,74.7),
 ('RES_son_emulsion_out','limpieza','convencional',127.0,129.0),
 ('AMP_cau_emulsion_out','limpieza','convencional',17.6,18.1),
 ('FRE_cau_emulsion_out','limpieza','convencional',323.0,346.0),
 ('AMP_niv_emulsion_dep','limpieza','convencional',5.04,17.8),
 ('DIS_niv_emulsion_dep','limpieza','convencional',2.05,14.0),
 ('AMP_eco_emulsion_dep','limpieza','convencional',57.0,63.0),
 ('RPM_motor_molino','limpieza','convencional',2892.0,2908.0),
 ('FRE_vfd_motor_molino','limpieza','convencional',49.9,50.1),
 ('AMP_vfd_motor_molino','limpieza','convencional',55.5,62.4),
 ('TOR_vfd_motor_molino','limpieza','convencional',37.7,42.0),
 ('VIB_vel_motor_molino','limpieza','convencional',1.86,4.5),
 ('AMP_vib_motor_molino','limpieza','convencional',5.19,7.39),
 ('CAU_bomba_lpm','limpieza','convencional',255.0,265.0),
 ('PRE_dif_filtro_bar','limpieza','convencional',0.314,1.1),
 ('TEM_emulsion_molino_out','limpieza','convencional',34.5,59.9),
 ('PRE_intercambiador_bar','limpieza','convencional',-0.01,0.01),
 ('TEM_son_betum_in','limpieza','plastomerico',174.0,189.0),
 ('RES_son_betum_in','limpieza','plastomerico',167.0,173.0),
 ('VOLT_son_betum_in','limpieza','plastomerico',22.8,24.0),
 ('AMP_son_betum_in','limpieza','plastomerico',15.1,16.1),
 ('AMP_cau_betum_in','limpieza','plastomerico',3.96,4.03),
 ('FRE_cau_betum_in','limpieza','plastomerico',245.0,249.0),
 ('AMP_niv_betum_dep','limpieza','plastomerico',8.62,16.5),
 ('DIS_niv_betum_dep','limpieza','plastomerico',3.28,10.7),
 ('POR_niv_betum_dep','limpieza','plastomerico',28.9,78.1),
 ('VOL_niv_betum_dep','limpieza','plastomerico',8662.0,23431.0),
 ('AMP_eco_betum_dep','limpieza','plastomerico',30.0,66.4),
 ('TEM_son_solucion_in','limpieza','plastomerico',44.4,45.6),
 ('RES_son_solucion_in','limpieza','plastomerico',117.0,118.0),
 ('AMP_son_solucion_in','limpieza','plastomerico',11.1,11.3),
 ('AMP_cau_solucion_in','limpieza','plastomerico',3.98,5.16),
 ('FRE_cau_solucion_in','limpieza','plastomerico',398.0,402.0),
 ('DIS_niv_solucion_dep','limpieza','plastomerico',8.76,11.3),
 ('POR_niv_solucion_dep','limpieza','plastomerico',24.7,41.6),
 ('AMP_eco_solucion_dep','limpieza','plastomerico',68.0,71.7),
 ('TEM_son_emulsion_out','limpieza','plastomerico',79.5,89.6),
 ('RES_son_emulsion_out','limpieza','plastomerico',131.0,135.0),
 ('AMP_cau_emulsion_out','limpieza','plastomerico',17.6,18.1),
 ('FRE_cau_emulsion_out','limpieza','plastomerico',323.0,346.0),
 ('AMP_niv_emulsion_dep','limpieza','plastomerico',5.57,17.7),
 ('DIS_niv_emulsion_dep','limpieza','plastomerico',2.19,13.5),
 ('AMP_eco_emulsion_dep','limpieza','plastomerico',57.2,63.1),
 ('RPM_motor_molino','limpieza','plastomerico',2892.0,2908.0),
 ('FRE_vfd_motor_molino','limpieza','plastomerico',49.9,50.1),
 ('AMP_vfd_motor_molino','limpieza','plastomerico',55.8,62.6),
 ('TOR_vfd_motor_molino','limpieza','plastomerico',37.7,42.0),
 ('VIB_vel_motor_molino','limpieza','plastomerico',1.85,4.5),
 ('AMP_vib_motor_molino','limpieza','plastomerico',5.18,8.0),
 ('CAU_bomba_lpm','limpieza','plastomerico',255.0,265.0),
 ('PRE_dif_filtro_bar','limpieza','plastomerico',0.328,1.1),
 ('TEM_emulsion_molino_out','limpieza','plastomerico',34.5,73.3),
 ('PRE_intercambiador_bar','limpieza','plastomerico',-0.01,0.01),
 ('TEM_son_betum_in','mantenimiento','ninguno',120.0,159.0),
 ('RES_son_betum_in','mantenimiento','ninguno',146.0,161.0),
 ('VOLT_son_betum_in','mantenimiento','ninguno',22.6,24.0),
 ('AMP_son_betum_in','mantenimiento','ninguno',11.7,14.2),
 ('AMP_cau_betum_in','mantenimiento','ninguno',3.96,4.04),
 ('FRE_cau_betum_in','mantenimiento','ninguno',248.0,252.0),
 ('AMP_niv_betum_dep','mantenimiento','ninguno',10.6,19.2),
 ('DIS_niv_betum_dep','mantenimiento','ninguno',0.732,8.83),
 ('POR_niv_betum_dep','mantenimiento','ninguno',41.1,95.1),
 ('VOL_niv_betum_dep','mantenimiento','ninguno',12342.0,28536.0),
 ('AMP_eco_betum_dep','mantenimiento','ninguno',31.4,63.0),
 ('TEM_son_solucion_in','mantenimiento','ninguno',29.6,35.6),
 ('RES_son_solucion_in','mantenimiento','ninguno',111.0,114.0),
 ('AMP_son_solucion_in','mantenimiento','ninguno',8.74,9.7),
 ('AMP_cau_solucion_in','mantenimiento','ninguno',3.97,5.32),
 ('FRE_cau_solucion_in','mantenimiento','ninguno',398.0,402.0),
 ('DIS_niv_solucion_dep','mantenimiento','ninguno',9.06,11.9),
 ('POR_niv_solucion_dep','mantenimiento','ninguno',20.5,39.6),
 ('AMP_eco_solucion_dep','mantenimiento','ninguno',68.0,72.1),
 ('TEM_son_emulsion_out','mantenimiento','ninguno',58.9,68.2),
 ('RES_son_emulsion_out','mantenimiento','ninguno',123.0,126.0),
 ('AMP_cau_emulsion_out','mantenimiento','ninguno',3.96,4.04),
 ('FRE_cau_emulsion_out','mantenimiento','ninguno',318.0,322.0),
 ('AMP_niv_emulsion_dep','mantenimiento','ninguno',6.3,12.6),
 ('DIS_niv_emulsion_dep','mantenimiento','ninguno',6.97,12.8),
 ('AMP_eco_emulsion_dep','mantenimiento','ninguno',56.9,62.7),
 ('RPM_motor_molino','mantenimiento','ninguno',-0.01,0.01),
 ('FRE_vfd_motor_molino','mantenimiento','ninguno',-0.01,0.01),
 ('AMP_vfd_motor_molino','mantenimiento','ninguno',-0.01,0.01),
 ('TOR_vfd_motor_molino','mantenimiento','ninguno',-0.01,0.01),
 ('VIB_vel_motor_molino','mantenimiento','ninguno',0.08,0.15),
 ('AMP_vib_motor_molino','mantenimiento','ninguno',4.05,4.09),
 ('CAU_bomba_lpm','mantenimiento','ninguno',-0.01,0.01),
 ('PRE_dif_filtro_bar','mantenimiento','ninguno',0.0,0.022),
 ('TEM_emulsion_molino_out','mantenimiento','ninguno',39.4,40.6),
 ('PRE_intercambiador_bar','mantenimiento','ninguno',-0.01,0.01),
 ('TEM_son_betum_in','preparacion','convencional',121.0,143.0),
 ('RES_son_betum_in','preparacion','convencional',147.0,155.0),
 ('VOLT_son_betum_in','preparacion','convencional',22.7,24.0),
 ('AMP_son_betum_in','preparacion','convencional',11.7,13.1),
 ('AMP_cau_betum_in','preparacion','convencional',3.96,4.04),
 ('FRE_cau_betum_in','preparacion','convencional',248.0,252.0),
 ('AMP_niv_betum_dep','preparacion','convencional',8.56,19.2),
 ('DIS_niv_betum_dep','preparacion','convencional',0.736,10.7),
 ('POR_niv_betum_dep','preparacion','convencional',28.5,95.1),
 ('VOL_niv_betum_dep','preparacion','convencional',8545.0,28529.0),
 ('AMP_eco_betum_dep','preparacion','convencional',27.7,65.9),
 ('TEM_son_solucion_in','preparacion','convencional',26.8,33.6),
 ('RES_son_solucion_in','preparacion','convencional',110.0,113.0),
 ('AMP_son_solucion_in','preparacion','convencional',8.29,9.38),
 ('AMP_cau_solucion_in','preparacion','convencional',3.98,5.35),
 ('FRE_cau_solucion_in','preparacion','convencional',398.0,402.0),
 ('DIS_niv_solucion_dep','preparacion','convencional',3.6,10.8),
 ('POR_niv_solucion_dep','preparacion','convencional',27.8,76.0),
 ('AMP_eco_solucion_dep','preparacion','convencional',68.0,72.0),
 ('TEM_son_emulsion_out','preparacion','convencional',47.9,73.3),
 ('RES_son_emulsion_out','preparacion','convencional',118.0,128.0),
 ('AMP_cau_emulsion_out','preparacion','convencional',3.96,4.04),
 ('FRE_cau_emulsion_out','preparacion','convencional',318.0,322.0),
 ('AMP_niv_emulsion_dep','preparacion','convencional',4.82,13.4),
 ('DIS_niv_emulsion_dep','preparacion','convencional',6.17,14.2),
 ('AMP_eco_emulsion_dep','preparacion','convencional',57.1,62.8),
 ('RPM_motor_molino','preparacion','convencional',-0.01,0.01),
 ('FRE_vfd_motor_molino','preparacion','convencional',-0.01,0.01),
 ('AMP_vfd_motor_molino','preparacion','convencional',-0.01,0.01),
 ('TOR_vfd_motor_molino','preparacion','convencional',-0.01,0.01),
 ('VIB_vel_motor_molino','preparacion','convencional',0.08,0.15),
 ('AMP_vib_motor_molino','preparacion','convencional',4.05,4.09),
 ('CAU_bomba_lpm','preparacion','convencional',-0.01,0.01),
 ('PRE_dif_filtro_bar','preparacion','convencional',0.0,0.022),
 ('TEM_emulsion_molino_out','preparacion','convencional',39.4,40.6),
 ('PRE_intercambiador_bar','preparacion','convencional',-0.01,0.01),
 ('TEM_son_betum_in','preparacion','plastomerico',167.0,188.0),
 ('RES_son_betum_in','preparacion','plastomerico',164.0,172.0),
 ('VOLT_son_betum_in','preparacion','plastomerico',22.9,24.0),
 ('AMP_son_betum_in','preparacion','plastomerico',14.7,16.0),
 ('AMP_cau_betum_in','preparacion','plastomerico',3.96,4.04),
 ('FRE_cau_betum_in','preparacion','plastomerico',245.0,249.0),
 ('AMP_niv_betum_dep','preparacion','plastomerico',8.71,19.2),
 ('DIS_niv_betum_dep','preparacion','plastomerico',0.735,10.6),
 ('POR_niv_betum_dep','preparacion','plastomerico',29.5,95.1),
 ('VOL_niv_betum_dep','preparacion','plastomerico',8837.0,28530.0),
 ('AMP_eco_betum_dep','preparacion','plastomerico',31.2,65.2),
 ('TEM_son_solucion_in','preparacion','plastomerico',28.0,41.3),
 ('RES_son_solucion_in','preparacion','plastomerico',111.0,116.0),
 ('AMP_son_solucion_in','preparacion','plastomerico',8.48,10.6),
 ('AMP_cau_solucion_in','preparacion','plastomerico',3.97,5.09),
 ('FRE_cau_solucion_in','preparacion','plastomerico',398.0,402.0),
 ('DIS_niv_solucion_dep','preparacion','plastomerico',3.59,10.9),
 ('POR_niv_solucion_dep','preparacion','plastomerico',27.3,76.1),
 ('AMP_eco_solucion_dep','preparacion','plastomerico',68.0,71.9),
 ('TEM_son_emulsion_out','preparacion','plastomerico',48.5,72.5),
 ('RES_son_emulsion_out','preparacion','plastomerico',119.0,128.0),
 ('AMP_cau_emulsion_out','preparacion','plastomerico',3.96,4.04),
 ('FRE_cau_emulsion_out','preparacion','plastomerico',318.0,322.0),
 ('AMP_niv_emulsion_dep','preparacion','plastomerico',4.74,13.4),
 ('DIS_niv_emulsion_dep','preparacion','plastomerico',6.2,14.3),
 ('AMP_eco_emulsion_dep','preparacion','plastomerico',57.1,63.2),
 ('RPM_motor_molino','preparacion','plastomerico',-0.01,0.01),
 ('FRE_vfd_motor_molino','preparacion','plastomerico',-0.01,0.01),
 ('AMP_vfd_motor_molino','preparacion','plastomerico',-0.01,0.01),
 ('TOR_vfd_motor_molino','preparacion','plastomerico',-0.01,0.01),
 ('VIB_vel_motor_molino','preparacion','plastomerico',0.08,0.15),
 ('AMP_vib_motor_molino','preparacion','plastomerico',4.05,4.09),
 ('CAU_bomba_lpm','preparacion','plastomerico',-0.01,0.01),
 ('PRE_dif_filtro_bar','preparacion','plastomerico',0.0,0.023),
 ('TEM_emulsion_molino_out','preparacion','plastomerico',39.4,40.6),
 ('PRE_intercambiador_bar','preparacion','plastomerico',-0.01,0.01),
 ('TEM_son_betum_in','produccion','convencional',126.0,140.0),
 ('RES_son_betum_in','produccion','convencional',148.0,154.0),
 ('VOLT_son_betum_in','produccion','convencional',22.6,24.0),
 ('AMP_son_betum_in','produccion','convencional',12.0,13.0),
 ('AMP_cau_betum_in','produccion','convencional',11.9,13.2),
 ('FRE_cau_betum_in','produccion','convencional',248.0,252.0),
 ('AMP_niv_betum_dep','produccion','convencional',8.91,18.6),
 ('DIS_niv_betum_dep','produccion','convencional',1.29,10.4),
 ('POR_niv_betum_dep','produccion','convencional',30.7,91.4),
 ('VOL_niv_betum_dep','produccion','convencional',9201.0,27417.0),
 ('AMP_eco_betum_dep','produccion','convencional',27.8,65.8),
 ('TEM_son_solucion_in','produccion','convencional',33.8,35.5),
 ('RES_son_solucion_in','produccion','convencional',113.0,114.0),
 ('AMP_son_solucion_in','produccion','convencional',9.41,9.68),
 ('AMP_cau_solucion_in','produccion','convencional',12.3,14.4),
 ('FRE_cau_solucion_in','produccion','convencional',398.0,402.0),
 ('DIS_niv_solucion_dep','produccion','convencional',3.88,11.1),
 ('POR_niv_solucion_dep','produccion','convencional',25.8,74.2),
 ('AMP_eco_solucion_dep','produccion','convencional',68.0,72.0),
 ('TEM_son_emulsion_out','produccion','convencional',61.1,74.6),
 ('RES_son_emulsion_out','produccion','convencional',124.0,129.0),
 ('AMP_cau_emulsion_out','produccion','convencional',12.5,13.8),
 ('FRE_cau_emulsion_out','produccion','convencional',318.0,322.0),
 ('AMP_niv_emulsion_dep','produccion','convencional',5.96,16.7),
 ('DIS_niv_emulsion_dep','produccion','convencional',3.09,13.2),
 ('AMP_eco_emulsion_dep','produccion','convencional',57.1,62.9),
 ('RPM_motor_molino','produccion','convencional',2891.0,2907.0),
 ('FRE_vfd_motor_molino','produccion','convencional',49.8,50.1),
 ('AMP_vfd_motor_molino','produccion','convencional',103.0,110.0),
 ('TOR_vfd_motor_molino','produccion','convencional',69.6,74.3),
 ('VIB_vel_motor_molino','produccion','convencional',1.88,4.5),
 ('AMP_vib_motor_molino','produccion','convencional',5.2,7.33),
 ('CAU_bomba_lpm','produccion','convencional',159.0,184.0),
 ('PRE_dif_filtro_bar','produccion','convencional',0.253,0.917),
 ('TEM_emulsion_molino_out','produccion','convencional',60.6,75.3),
 ('PRE_intercambiador_bar','produccion','convencional',-0.01,0.01),
 ('TEM_son_betum_in','produccion','plastomerico',177.0,190.0),
 ('RES_son_betum_in','produccion','plastomerico',168.0,173.0),
 ('VOLT_son_betum_in','produccion','plastomerico',22.8,24.0),
 ('AMP_son_betum_in','produccion','plastomerico',15.3,16.1),
 ('AMP_cau_betum_in','produccion','plastomerico',12.3,13.6),
 ('FRE_cau_betum_in','produccion','plastomerico',245.0,249.0),
 ('AMP_niv_betum_dep','produccion','plastomerico',8.87,18.5),
 ('DIS_niv_betum_dep','produccion','plastomerico',1.36,10.4),
 ('POR_niv_betum_dep','produccion','plastomerico',30.5,90.9),
 ('VOL_niv_betum_dep','produccion','plastomerico',9138.0,27280.0),
 ('AMP_eco_betum_dep','produccion','plastomerico',29.2,65.6),
 ('TEM_son_solucion_in','produccion','plastomerico',42.6,45.5),
 ('RES_son_solucion_in','produccion','plastomerico',116.0,117.0),
 ('AMP_son_solucion_in','produccion','plastomerico',10.8,11.3),
 ('AMP_cau_solucion_in','produccion','plastomerico',11.7,13.6),
 ('FRE_cau_solucion_in','produccion','plastomerico',398.0,402.0),
 ('DIS_niv_solucion_dep','produccion','plastomerico',3.86,10.6),
 ('POR_niv_solucion_dep','produccion','plastomerico',29.6,74.2),
 ('AMP_eco_solucion_dep','produccion','plastomerico',68.0,71.9),
 ('TEM_son_emulsion_out','produccion','plastomerico',66.1,87.6),
 ('RES_son_emulsion_out','produccion','plastomerico',125.0,134.0),
 ('AMP_cau_emulsion_out','produccion','plastomerico',12.5,13.8),
 ('FRE_cau_emulsion_out','produccion','plastomerico',318.0,322.0),
 ('AMP_niv_emulsion_dep','produccion','plastomerico',5.75,16.4),
 ('DIS_niv_emulsion_dep','produccion','plastomerico',3.41,13.4),
 ('AMP_eco_emulsion_dep','produccion','plastomerico',56.9,62.9),
 ('RPM_motor_molino','produccion','plastomerico',2882.0,2898.0),
 ('FRE_vfd_motor_molino','produccion','plastomerico',49.7,50.0),
 ('AMP_vfd_motor_molino','produccion','plastomerico',114.0,121.0),
 ('TOR_vfd_motor_molino','produccion','plastomerico',77.1,82.1),
 ('VIB_vel_motor_molino','produccion','plastomerico',1.9,4.5),
 ('AMP_vib_motor_molino','produccion','plastomerico',5.22,7.64),
 ('CAU_bomba_lpm','produccion','plastomerico',159.0,184.0),
 ('PRE_dif_filtro_bar','produccion','plastomerico',0.256,0.926),
 ('TEM_emulsion_molino_out','produccion','plastomerico',73.0,95.5),
 ('PRE_intercambiador_bar','produccion','plastomerico',2.45,3.62);

INSERT INTO rangos_operacion (sensor_id, estado, tipo_asfalto, normal_min, normal_max)
SELECT s.id, r.estado, r.tipo_asfalto, r.normal_min, r.normal_max
FROM rangos_tmp r JOIN sensores s ON s.tag = r.tag;

-- =====================================================================
-- 3. REGLAS FIJAS (HU-11). No dependen de los modelos.
--    solo_en_marcha: se evalúa solo en producción o limpieza.
-- =====================================================================
CREATE TABLE reglas_alarma (
    id              SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo          VARCHAR(40)   NOT NULL UNIQUE,
    sensor_id       INTEGER       NOT NULL REFERENCES sensores (id),
    comparacion     CHAR(1)       NOT NULL CHECK (comparacion IN ('>', '<')),
    limite          NUMERIC(12,3) NOT NULL,
    tipo_asfalto    VARCHAR(15)   CHECK (tipo_asfalto IN ('convencional', 'plastomerico')), -- NULL = ambos
    solo_en_marcha  BOOLEAN       NOT NULL,
    prioridad       VARCHAR(10)   NOT NULL CHECK (prioridad IN ('baja', 'media', 'alta')),
    componente      VARCHAR(20),
    mensaje         VARCHAR(120)  NOT NULL,
    accion          VARCHAR(250),
    activa          BOOLEAN       NOT NULL DEFAULT TRUE
);

INSERT INTO reglas_alarma (codigo, sensor_id, comparacion, limite, tipo_asfalto, solo_en_marcha,
                           prioridad, componente, mensaje, accion)
SELECT r.codigo, s.id, r.comparacion, r.limite, r.tipo_asfalto, r.solo_en_marcha,
       r.prioridad, r.componente, r.mensaje, r.accion
FROM (VALUES
 ('LAZO_CAUDAL_SOL_ALTO', 'AMP_cau_solucion_in', '>', 21,   NULL, FALSE, 'alta', 'FT-201',
  'Lazo del caudalímetro de solución sobre 21 mA', 'Revisar el lazo 4-20 mA de FT-201 (posible cortocircuito).'),
 ('PT100_SIN_ALIMENTACION', 'VOLT_son_betum_in',  '<', 20,   NULL, FALSE, 'alta', 'TT-101',
  'Alimentación de la Pt100 del betún bajo 20 V', 'Revisar fuente de 24 V y borneras de la Pt100 de TK-101.'),
 ('LAZO_CAUDAL_EMU_BAJO', 'AMP_cau_emulsion_out', '<', 3.6, NULL, FALSE, 'alta', 'TK-301',
  'Lazo del caudal de emulsión bajo 3,6 mA', 'Revisar el lazo 4-20 mA del caudalímetro de emulsión (posible corte).'),
 ('VIBRACION_ALTA',       'VIB_vel_motor_molino', '>', 4.5, NULL, TRUE,  'alta', 'MC-01',
  'Vibración del molino sobre 4,5 mm/s', 'Revisar rodamientos y alineación del molino MC-01.'),
 ('CORRIENTE_ALTA',       'AMP_vfd_motor_molino', '>', 130, NULL, TRUE,  'alta', 'MC-01',
  'Corriente del motor sobre 130 A', 'Reducir carga y revisar temperatura del betún.'),
 ('DP_FILTRO_ALTA',       'PRE_dif_filtro_bar',   '>', 1.1, NULL, TRUE,  'media', 'F-101',
  'ΔP del filtro sobre 1,1 bar', 'Programar limpieza del filtro F-101.'),
 ('BETUN_FRIO_CONV',      'TEM_son_betum_in',     '<', 125, 'convencional', TRUE, 'media', 'TK-101',
  'Temperatura del betún bajo 125 °C (convencional)', 'Revisar caldera y calefacción de TK-101.'),
 ('BETUN_FRIO_PLASTO',    'TEM_son_betum_in',     '<', 175, 'plastomerico', TRUE, 'media', 'TK-101',
  'Temperatura del betún bajo 175 °C (plastomérico)', 'Revisar caldera y calefacción de TK-101.')
) AS r (codigo, tag, comparacion, limite, tipo_asfalto, solo_en_marcha, prioridad, componente, mensaje, accion)
JOIN sensores s ON s.tag = r.tag;

-- =====================================================================
-- 4. PREDICCIONES: más datos de cada modelo
--    modelo 'diagnostico' y 'autoencoder': 1 fila por minuto (horizonte 'actual')
--    modelo 'predictivo': 1 fila por hora, falla y horizonte (24h, 5d, 15d)
-- =====================================================================
ALTER TABLE predicciones
    ADD COLUMN metodo          VARCHAR(20),          -- LightGBM, Tendencia, Autoencoder
    ADD COLUMN umbral          NUMERIC(10,4),        -- umbral de alerta del modelo
    ADD COLUMN alerta          BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN dias_estimados  NUMERIC(10,2),        -- fallas raras: días hasta el límite físico
    ADD COLUMN error_ae        NUMERIC(14,4),        -- error de reconstrucción del autoencoder
    ADD COLUMN detalle         JSONB;                -- sensores que más aportan, probabilidades

ALTER TABLE predicciones ALTER COLUMN indice_salud TYPE NUMERIC(8,2);

DO $$
DECLARE c TEXT;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'mantpred.predicciones'::regclass AND contype = 'u' LOOP
        EXECUTE format('ALTER TABLE mantpred.predicciones DROP CONSTRAINT %I', c);
    END LOOP;
END $$;

CREATE UNIQUE INDEX ux_pred_tiempo_real ON predicciones (equipo_id, fuente, modelo, ts)
    WHERE modelo IN ('diagnostico', 'autoencoder');
CREATE UNIQUE INDEX ux_pred_predictivo ON predicciones (equipo_id, fuente, tipo_falla_id, horizonte, ts)
    WHERE modelo = 'predictivo';
DROP INDEX IF EXISTS ix_pred_equipo_ts;
CREATE INDEX ix_pred_equipo_modelo_ts ON predicciones (equipo_id, fuente, modelo, ts DESC);

-- =====================================================================
-- 5. CONDICIONES ANÓMALAS POR MINUTO (base de la regla "3 de los últimos 5 minutos")
-- =====================================================================
CREATE TABLE condiciones_minuto (
    equipo_id      INTEGER       NOT NULL REFERENCES equipos (id),
    fuente         VARCHAR(10)   NOT NULL CHECK (fuente IN ('real', 'simulado')),
    ts             TIMESTAMPTZ   NOT NULL,                         -- minuto exacto
    clave          VARCHAR(80)   NOT NULL,                         -- modelo:<falla> o regla:<codigo>
    origen         VARCHAR(10)   NOT NULL CHECK (origen IN ('modelo', 'regla')),
    tipo_falla_id  SMALLINT      REFERENCES tipos_falla (id),
    regla_id       SMALLINT      REFERENCES reglas_alarma (id),
    valor          NUMERIC(14,4),
    PRIMARY KEY (equipo_id, fuente, ts, clave)
);

-- =====================================================================
-- 6. ALARMAS: regla de origen y una sola alarma activa por causa
-- =====================================================================
ALTER TABLE alarmas ADD COLUMN regla_id SMALLINT REFERENCES reglas_alarma (id);
ALTER TABLE alarmas ADD COLUMN clave    VARCHAR(80);         -- misma clave que condiciones_minuto
ALTER TABLE alarmas ADD COLUMN detalle  JSONB;               -- origen del diagnóstico, sensores
CREATE UNIQUE INDEX ux_alarma_activa ON alarmas (equipo_id, fuente, clave) WHERE fin IS NULL;
CREATE INDEX ix_alarmas_fuente_inicio ON alarmas (fuente, inicio DESC);

-- =====================================================================
-- 7. MANTENIMIENTOS: la bitácora llega desde la planta (solo lectura en el dashboard)
-- =====================================================================
ALTER TABLE mantenimientos ALTER COLUMN registrado_por DROP NOT NULL;
ALTER TABLE mantenimientos
    ADD COLUMN fuente           VARCHAR(10) NOT NULL DEFAULT 'real'
                                CHECK (fuente IN ('real', 'simulado')),
    ADD COLUMN origen_registro  VARCHAR(10) NOT NULL DEFAULT 'dashboard'
                                CHECK (origen_registro IN ('bitacora', 'dashboard'));
ALTER TABLE mantenimientos ALTER COLUMN componente TYPE VARCHAR(80);

-- Bitácora del año simulado (Bitacora_Mantenimiento_QLA.csv), hora local de Chile
INSERT INTO mantenimientos (equipo_id, componente, tipo, tipo_falla_id, fecha_inicio, descripcion, fuente, origen_registro)
SELECT (SELECT id FROM equipos WHERE codigo = 'MC-01'), b.componente, b.tipo, b.tipo_falla_id,
       b.fecha::timestamp AT TIME ZONE 'America/Santiago', b.descripcion, 'simulado', 'bitacora'
FROM (VALUES
 ('2026-01-03 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; lubricación de rodamientos'),
 ('2026-01-27 12:47:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-01-30 13:07:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-02-07 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; secado y sellado del transmisor de caudal; cambio preventivo de rodamientos por vibración alta'),
 ('2026-02-09 11:53:00', 'TT-101 Pt100 betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Falla_Electrica_PT100_Betun'), 'Reparación de cableado y borneras de la Pt100'),
 ('2026-02-13 18:29:00', 'TK-101 caldera / calefactor de betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Sobrecarga_Motor_Por_Asfalto_Frio'), 'Reparación de caldera / resistencia de calefacción del betún'),
 ('2026-02-20 16:51:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-02-26 13:18:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-03-07 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; mantención de caldera; lubricación de rodamientos'),
 ('2026-03-30 12:49:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-03-30 15:03:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-04-04 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; mantención de caldera; lubricación de rodamientos'),
 ('2026-04-06 10:11:00', 'TK-101 caldera / calefactor de betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Sobrecarga_Motor_Por_Asfalto_Frio'), 'Reparación de caldera / resistencia de calefacción del betún'),
 ('2026-04-22 19:10:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-04-27 09:50:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-04-30 19:10:00', 'E-301 intercambiador de calor', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Ensuciamiento_Intercambiador'), 'Limpieza química del intercambiador'),
 ('2026-05-02 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; mantención de caldera; cambio preventivo de rodamientos por vibración alta'),
 ('2026-05-05 19:17:00', 'FT-201 caudalímetro solución', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Cortocircuito_Transmisor_Caudal_Sol'), 'Cambio de transmisor de caudal de solución por cortocircuito'),
 ('2026-05-27 11:54:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-05-27 17:46:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-06-02 18:11:00', 'E-301 intercambiador de calor', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Ensuciamiento_Intercambiador'), 'Limpieza química del intercambiador'),
 ('2026-06-03 10:43:00', 'TT-101 Pt100 betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Falla_Electrica_PT100_Betun'), 'Reparación de cableado y borneras de la Pt100'),
 ('2026-06-06 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; lubricación de rodamientos'),
 ('2026-06-09 16:12:00', 'FT-201 caudalímetro solución', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Cortocircuito_Transmisor_Caudal_Sol'), 'Cambio de transmisor de caudal de solución por cortocircuito'),
 ('2026-06-11 20:46:00', 'TK-101 caldera / calefactor de betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Sobrecarga_Motor_Por_Asfalto_Frio'), 'Reparación de caldera / resistencia de calefacción del betún'),
 ('2026-06-19 16:48:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-06-29 11:06:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-07-04 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; mantención de caldera; lubricación de rodamientos'),
 ('2026-07-13 11:41:00', 'TT-101 Pt100 betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Falla_Electrica_PT100_Betun'), 'Reparación de cableado y borneras de la Pt100'),
 ('2026-07-15 12:07:00', 'FT-201 caudalímetro solución', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Cortocircuito_Transmisor_Caudal_Sol'), 'Cambio de transmisor de caudal de solución por cortocircuito'),
 ('2026-07-21 14:37:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-07-28 12:44:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-07-29 12:16:00', 'MC-01 rodamientos del molino', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Desgaste_Rodamientos_Molino'), 'Cambio de rodamientos del molino'),
 ('2026-07-31 13:42:00', 'E-301 intercambiador de calor', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Ensuciamiento_Intercambiador'), 'Limpieza química del intercambiador'),
 ('2026-08-01 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; mantención de caldera; lubricación de rodamientos'),
 ('2026-08-17 12:45:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-08-18 10:48:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-08-24 18:34:00', 'FT-201 caudalímetro solución', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Cortocircuito_Transmisor_Caudal_Sol'), 'Cambio de transmisor de caudal de solución por cortocircuito'),
 ('2026-08-27 16:17:00', 'E-301 intercambiador de calor', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Ensuciamiento_Intercambiador'), 'Limpieza química del intercambiador'),
 ('2026-09-04 13:46:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-09-05 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; mantención de caldera; lubricación de rodamientos'),
 ('2026-09-21 11:33:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-09-24 13:48:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-10-01 17:02:00', 'MC-01 rodamientos del molino', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Desgaste_Rodamientos_Molino'), 'Cambio de rodamientos del molino'),
 ('2026-10-03 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; mantención de caldera; lubricación de rodamientos'),
 ('2026-10-05 12:49:00', 'TK-101 caldera / calefactor de betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Sobrecarga_Motor_Por_Asfalto_Frio'), 'Reparación de caldera / resistencia de calefacción del betún'),
 ('2026-10-21 16:34:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-10-28 11:29:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-10-28 19:14:00', 'E-301 intercambiador de calor', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Ensuciamiento_Intercambiador'), 'Limpieza química del intercambiador'),
 ('2026-11-03 15:43:00', 'TK-101 caldera / calefactor de betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Sobrecarga_Motor_Por_Asfalto_Frio'), 'Reparación de caldera / resistencia de calefacción del betún'),
 ('2026-11-03 18:07:00', 'FT-201 caudalímetro solución', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Cortocircuito_Transmisor_Caudal_Sol'), 'Cambio de transmisor de caudal de solución por cortocircuito'),
 ('2026-11-07 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; lubricación de rodamientos'),
 ('2026-11-23 09:39:00', 'TT-101 Pt100 betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Falla_Electrica_PT100_Betun'), 'Reparación de cableado y borneras de la Pt100'),
 ('2026-11-23 15:08:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto'),
 ('2026-11-27 13:53:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-12-01 10:03:00', 'TK-101 caldera / calefactor de betún', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Sobrecarga_Motor_Por_Asfalto_Frio'), 'Reparación de caldera / resistencia de calefacción del betún'),
 ('2026-12-05 14:00:00', 'Planta completa', 'preventivo', NULL, 'Limpieza de filtro, intercambiador y antena del radar; reapriete de borneras de instrumentación; secado y sellado del transmisor de caudal; lubricación de rodamientos'),
 ('2026-12-22 13:32:00', 'F-101 filtro de línea', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Filtro_Obstruido'), 'Limpieza correctiva de filtro obstruido'),
 ('2026-12-24 14:25:00', 'E-301 intercambiador de calor', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Ensuciamiento_Intercambiador'), 'Limpieza química del intercambiador'),
 ('2026-12-28 11:38:00', 'TK-101 radar de nivel', 'correctivo', (SELECT id FROM tipos_falla WHERE codigo = 'Advertencia_Radar_Sucio_Betun'), 'Limpieza de antena del radar por costra de asfalto')
) AS b (fecha, componente, tipo, tipo_falla_id, descripcion)
WHERE NOT EXISTS (SELECT 1 FROM mantenimientos m WHERE m.origen_registro = 'bitacora' AND m.fuente = 'simulado');

-- =====================================================================
-- 8. RETENCIÓN: borra lo simulado más antiguo que N días (respecto al último dato)
--    Uso: SELECT * FROM mantpred.purgar_datos_simulados(14);
-- =====================================================================
CREATE FUNCTION purgar_datos_simulados(dias INTEGER)
RETURNS TABLE (tabla TEXT, filas BIGINT) LANGUAGE plpgsql AS $$
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

-- =====================================================================
-- 9. RLS en las tablas nuevas (solo el backend, conectado como postgres, las lee)
-- =====================================================================
ALTER TABLE rangos_operacion   ENABLE ROW LEVEL SECURITY;
ALTER TABLE reglas_alarma      ENABLE ROW LEVEL SECURITY;
ALTER TABLE condiciones_minuto ENABLE ROW LEVEL SECURITY;

COMMIT;

-- =====================================================================
-- COMPROBACIÓN (ejecutar después)
--   SELECT nombre, nivel FROM mantpred.roles;                          -- administrador 4, operador 2
--   SELECT count(*) FROM mantpred.rangos_operacion;                    -- 432
--   SELECT codigo, prioridad FROM mantpred.reglas_alarma;              -- 8 reglas
--   SELECT tipo, count(*) FROM mantpred.mantenimientos GROUP BY tipo;  -- correctivo 48, preventivo 12
-- =====================================================================
