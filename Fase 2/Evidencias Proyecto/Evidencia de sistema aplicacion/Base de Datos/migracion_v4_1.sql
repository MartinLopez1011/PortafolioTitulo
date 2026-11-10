-- =====================================================================
-- Proyecto : Mantenimiento predictivo inteligente – Química Latinoamericana S.A.
-- Archivo  : migracion_v4_1.sql
-- Aplica   : sobre el esquema mantpred versión 4 (migracion_v4.sql)
--
-- Qué cambia y por qué:
--   sensores y mantenimientos guardan equipo_id y componente_id. El equipo
--   también se deduce del componente (componente -> equipo), así que ambos
--   datos deben coincidir. Hasta v4 eso lo aseguraba el código; desde v4.1
--   lo asegura la base con una clave foránea compuesta:
--       (componente_id, equipo_id) -> componentes (id, equipo_id)
--   Reemplaza a la FK simple componente_id -> componentes(id), que queda
--   contenida en la compuesta.
--   En mantenimientos, componente_id NULL (= toda la línea) no se verifica
--   (MATCH SIMPLE), que es lo esperado.
--
-- Se ejecuta en una sola transacción: si algo falla no se aplica nada.
-- =====================================================================
BEGIN;
SET LOCAL search_path TO mantpred, public;

-- 0. Comprobación previa: no puede haber filas incoherentes
DO $$
DECLARE n_s int; n_m int;
BEGIN
    SELECT count(*) INTO n_s FROM sensores s JOIN componentes c ON c.id = s.componente_id
     WHERE c.equipo_id <> s.equipo_id;
    SELECT count(*) INTO n_m FROM mantenimientos m JOIN componentes c ON c.id = m.componente_id
     WHERE c.equipo_id <> m.equipo_id;
    IF n_s + n_m > 0 THEN
        RAISE EXCEPTION 'Hay % sensores y % mantenimientos cuyo equipo no coincide con el de su componente', n_s, n_m;
    END IF;
END $$;

-- 1. Clave candidata (id, equipo_id) en componentes, necesaria para la FK compuesta
ALTER TABLE componentes ADD CONSTRAINT componentes_id_equipo_key UNIQUE (id, equipo_id);

-- 2. sensores
ALTER TABLE sensores DROP CONSTRAINT sensores_componente_id_fkey;
ALTER TABLE sensores ADD CONSTRAINT sensores_componente_equipo_fkey
    FOREIGN KEY (componente_id, equipo_id) REFERENCES componentes (id, equipo_id);

-- 3. mantenimientos
ALTER TABLE mantenimientos DROP CONSTRAINT mantenimientos_componente_id_fkey;
ALTER TABLE mantenimientos ADD CONSTRAINT mantenimientos_componente_equipo_fkey
    FOREIGN KEY (componente_id, equipo_id) REFERENCES componentes (id, equipo_id);

COMMENT ON CONSTRAINT sensores_componente_equipo_fkey ON sensores IS
    'El componente del sensor debe pertenecer al mismo equipo que el sensor';
COMMENT ON CONSTRAINT mantenimientos_componente_equipo_fkey ON mantenimientos IS
    'El componente intervenido debe pertenecer al equipo de la mantención (sin componente = toda la línea)';

COMMIT;
