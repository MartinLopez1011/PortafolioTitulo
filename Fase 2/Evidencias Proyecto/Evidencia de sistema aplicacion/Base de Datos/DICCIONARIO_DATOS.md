# Diccionario de datos — esquema `mantpred` (v4)

Base PostgreSQL en Amazon RDS (`qla-mantpred`). 16 tablas en 5 áreas. Se construye con `bd_mantenimiento_predictivo_v2.sql`, `migracion_v3.sql` y `migracion_v4.sql`.

Claves: **PK** primaria · **FK** foránea · **UQ** única. *Nulo*: sí = admite valores vacíos.

## Planta y sensores

### `equipos`

Equipos monitoreados. Hoy, el molino coloidal MC-01

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | integer | PK | no | Identificador |
| `codigo` | varchar(20) | UQ | no | Código del equipo (MC-01) |
| `nombre` | varchar(100) | UQ | no | Nombre |
| `tipo` | varchar(60) |  | no | Tipo de equipo |
| `marca` | varchar(60) |  | sí | Marca |
| `modelo` | varchar(60) |  | sí | Modelo |
| `potencia` | varchar(40) |  | sí | Potencia nominal |
| `ubicacion` | varchar(120) |  | sí | Ubicación en la planta |

### `componentes`

Partes de la línea del equipo (estanques, instrumentos, filtro, bomba, válvula, molino, intercambiador), identificadas por su tag de planta

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | smallint | PK | no | Identificador |
| `equipo_id` | integer | FK → equipos | no | Equipo al que pertenece |
| `codigo` | varchar(20) | UQ | no | Tag de planta (TK-101, F-101…) |
| `nombre` | varchar(80) |  | no | Nombre del componente |
| `tipo` | varchar(20) |  | no | estanque, instrumento, filtro, bomba, válvula, molino o intercambiador |

Reglas de integridad (CHECK):

- `(tipo IN ('estanque', 'instrumento', 'filtro', 'bomba', 'valvula', 'molino', 'intercambiador'))`

### `sensores`

Catálogo de señales medidas: 41 del dataset simulado y 6 tags reales del PLC. normal_min/normal_max = banda general cuando no hay banda por modo en rangos_operacion

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | integer | PK | no | Identificador |
| `equipo_id` | integer | FK → equipos | no | Equipo |
| `tag` | varchar(40) | UQ | no | Nombre de la variable (igual que en el dataset y el PLC) |
| `nombre` | varchar(80) |  | no | Nombre legible |
| `variable` | varchar(40) |  | no | Magnitud (temperatura, presión, caudal…) |
| `tipo_sensor` | varchar(80) |  | no | Instrumento que la mide |
| `unidad` | varchar(15) |  | no | Unidad de medida |
| `rango_min` | numeric(12,3) |  | sí | Mínimo físico del instrumento |
| `rango_max` | numeric(12,3) |  | sí | Máximo físico del instrumento |
| `normal_min` | numeric(12,3) |  | sí | Banda normal general (si no hay banda por modo) |
| `normal_max` | numeric(12,3) |  | sí | Banda normal general (si no hay banda por modo) |
| `senal` | varchar(20) |  | no | Tipo de señal (4-20 mA, digital…) |
| `origen` | varchar(10) |  | no | simulado (dataset) o real (tag del PLC) |
| `activo` | boolean |  | no | Si se usa actualmente |
| `descripcion` | varchar(250) |  | sí | Descripción |
| `componente_id` | smallint | FK → componentes | no | Componente donde está montado |

Reglas de integridad (CHECK):

- `(((normal_min IS NULL) OR (normal_max IS NULL) OR (normal_min <= normal_max)))`
- `(origen IN ('real', 'simulado'))`
- `(((rango_min IS NULL) OR (rango_max IS NULL) OR (rango_min < rango_max)))`

### `lecturas`

Valor de cada sensor por minuto. Una fila por sensor, fuente y minuto

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | bigint | PK | no | Identificador |
| `sensor_id` | integer | FK → sensores | no | Sensor |
| `ts` | timestamptz |  | no | Minuto de la lectura |
| `valor` | numeric(12,3) |  | sí | Valor medido |
| `calidad` | varchar(10) |  | no | buena, dudosa o mala |
| `fuente` | varchar(10) |  | no | simulado o real |

Restricciones de unicidad:

- `(sensor_id, fuente, ts)`

Reglas de integridad (CHECK):

- `(calidad IN ('buena', 'dudosa', 'mala'))`
- `(fuente IN ('real', 'simulado'))`

### `estados_equipo`

Modo de operación del equipo por minuto (producción, limpieza, espera, preparación, detenida) y tipo de asfalto

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | bigint | PK | no | Identificador |
| `equipo_id` | integer | FK → equipos | no | Equipo |
| `ts` | timestamptz |  | no | Minuto |
| `estado` | varchar(15) |  | no | producción, limpieza, espera, preparación, detenida… |
| `tipo_asfalto` | varchar(15) |  | sí | convencional, plastomérico o ninguno |
| `fuente` | varchar(10) |  | no | simulado o real |

Restricciones de unicidad:

- `(equipo_id, fuente, ts)`

Reglas de integridad (CHECK):

- `(estado IN ('detenida', 'preparacion', 'produccion', 'espera', 'limpieza', 'mantenimiento', 'falla'))`
- `(fuente IN ('real', 'simulado'))`
- `(tipo_asfalto IN ('convencional', 'plastomerico', 'ninguno'))`

### `rangos_operacion`

Banda normal de cada sensor según modo de operación y tipo de asfalto (percentiles 2,5 y 97,5 de la operación sana)

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | integer | PK | no | Identificador |
| `sensor_id` | integer | FK → sensores | no | Sensor |
| `estado` | varchar(15) |  | no | Modo de operación |
| `tipo_asfalto` | varchar(15) |  | no | Tipo de asfalto |
| `normal_min` | numeric(12,3) |  | no | Percentil 2,5 de la operación sana |
| `normal_max` | numeric(12,3) |  | no | Percentil 97,5 de la operación sana |

Restricciones de unicidad:

- `(sensor_id, estado, tipo_asfalto)`

Reglas de integridad (CHECK):

- `(estado IN ('detenida', 'preparacion', 'produccion', 'espera', 'limpieza', 'mantenimiento'))`
- `(tipo_asfalto IN ('convencional', 'plastomerico', 'ninguno'))`
- `((normal_min <= normal_max))`

## Modelos de IA

### `tipos_falla`

Modos de falla que reconocen los modelos: 7 fallas y la anomalía desconocida

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | smallint | PK | no | Identificador |
| `codigo` | varchar(60) | UQ | no | Código que usan los modelos |
| `titulo` | varchar(100) |  | no | Nombre para el operador |
| `prioridad` | varchar(10) |  | no | baja, media o alta |
| `accion` | varchar(250) |  | sí | Acción sugerida |
| `componente_id` | smallint | FK → componentes | sí | Componente afectado (vacío en la anomalía desconocida) |

Reglas de integridad (CHECK):

- `(prioridad IN ('baja', 'media', 'alta'))`

### `predicciones`

Resultados de los 3 modelos. diagnostico y autoencoder: uno por minuto (horizonte actual). predictivo: uno por hora, falla y horizonte (24h, 5d, 15d)

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | bigint | PK | no | Identificador |
| `equipo_id` | integer | FK → equipos | no | Equipo |
| `ts` | timestamptz |  | no | Minuto (diagnóstico y autoencoder) u hora (predictivo) |
| `modelo` | varchar(15) |  | no | diagnostico, autoencoder o predictivo |
| `modelo_version` | varchar(30) |  | no | Versión del modelo |
| `horizonte` | varchar(6) |  | no | actual, 24h, 5d o 15d |
| `tipo_falla_id` | smallint | FK → tipos_falla | sí | Falla identificada o pronosticada |
| `prob_falla` | numeric(5,4) |  | sí | Probabilidad (0 a 1) |
| `indice_salud` | numeric(8,2) |  | sí | Índice de salud 0-100 (autoencoder) |
| `fuente` | varchar(10) |  | no | simulado o real |
| `metodo` | varchar(20) |  | sí | LightGBM, Tendencia o Autoencoder |
| `umbral` | numeric(10,4) |  | sí | Umbral de alerta |
| `alerta` | boolean |  | no | Si supera el umbral |
| `dias_estimados` | numeric(10,2) |  | sí | Días hasta el límite físico (fallas raras) |
| `error_ae` | numeric(14,4) |  | sí | Error de reconstrucción del autoencoder |
| `detalle` | jsonb |  | sí | Datos adicionales (sensores más desviados, confianza) |

Restricciones de unicidad:

- `(equipo_id, fuente, tipo_falla_id, horizonte, ts)` cuando `modelo = 'predictivo'`
- `(equipo_id, fuente, modelo, ts)` cuando `modelo IN ('diagnostico', 'autoencoder')`

Reglas de integridad (CHECK):

- `((((modelo) <> 'autoencoder') OR ((tipo_falla_id IS NULL) AND (prob_falla IS NULL))))`
- `((((modelo) <> 'diagnostico') OR (error_ae IS NULL)))`
- `((((modelo) <> 'predictivo') OR (tipo_falla_id IS NOT NULL)))`
- `((((modelo) = 'predictivo') = ((horizonte) <> 'actual')))`
- `(fuente IN ('real', 'simulado'))`
- `(horizonte IN ('actual', '24h', '5d', '15d'))`
- `(modelo IN ('diagnostico', 'autoencoder', 'predictivo'))`
- `(((prob_falla >= (0)) AND (prob_falla <= (1))))`

## Alarmas

### `reglas_alarma`

Reglas fijas sobre un sensor: límites de instrumento y de proceso

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | smallint | PK | no | Identificador |
| `codigo` | varchar(40) | UQ | no | Código de la regla |
| `sensor_id` | integer | FK → sensores | no | Sensor que evalúa |
| `comparacion` | char(1) |  | no | > o < |
| `limite` | numeric(12,3) |  | no | Valor límite |
| `tipo_asfalto` | varchar(15) |  | sí | Solo para ese tipo de asfalto (vacío = siempre) |
| `solo_en_marcha` | boolean |  | no | Si se evalúa solo con el molino en marcha |
| `prioridad` | varchar(10) |  | no | baja, media o alta |
| `mensaje` | varchar(120) |  | no | Texto de la alarma |
| `accion` | varchar(250) |  | sí | Acción sugerida |
| `activa` | boolean |  | no | Si la regla está vigente |

Reglas de integridad (CHECK):

- `(prioridad IN ('baja', 'media', 'alta'))`
- `(tipo_asfalto IN ('convencional', 'plastomerico'))`
- `((comparacion = ANY (ARRAY['>'::bpchar, '<'::bpchar])))`

### `condiciones_minuto`

Condiciones de alarma que se cumplieron cada minuto (modelo o regla). Base de la regla 3 de 5

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `equipo_id` | integer | PK, FK → equipos | no | Equipo |
| `fuente` | varchar(10) | PK | no | simulado o real |
| `ts` | timestamptz | PK | no | Minuto |
| `clave` | varchar(80) | PK | no | modelo:<falla> o regla:<código> |
| `origen` | varchar(10) |  | no | modelo o regla |
| `tipo_falla_id` | smallint | FK → tipos_falla | sí | Falla (origen modelo) |
| `regla_id` | smallint | FK → reglas_alarma | sí | Regla (origen regla) |
| `valor` | numeric(14,4) |  | sí | Valor que la gatilló |

Reglas de integridad (CHECK):

- `(fuente IN ('real', 'simulado'))`
- `(origen IN ('modelo', 'regla'))`

### `alarmas`

Alarmas abiertas y cerradas. Origen modelo (tipo_falla_id) o regla (regla_id). Una sola activa por clave

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | bigint | PK | no | Identificador |
| `equipo_id` | integer | FK → equipos | no | Equipo |
| `origen` | varchar(10) |  | no | modelo o regla |
| `tipo_falla_id` | smallint | FK → tipos_falla | sí | Falla (origen modelo) |
| `inicio` | timestamptz |  | no | Primer minuto de la condición |
| `fin` | timestamptz |  | sí | Cierre (vacío = activa) |
| `valor` | numeric(12,3) |  | sí | Valor al abrirse |
| `severidad` | varchar(12) |  | no | aviso, advertencia o crítica |
| `mensaje` | varchar(250) |  | sí | Texto de la alarma |
| `fuente` | varchar(10) |  | no | simulado o real |
| `reconocida_por` | integer | FK → usuarios | sí | Usuario que la reconoció |
| `reconocida_en` | timestamptz |  | sí | Fecha del reconocimiento |
| `comentario` | varchar(250) |  | sí | Comentario del reconocimiento |
| `regla_id` | smallint | FK → reglas_alarma | sí | Regla (origen regla) |
| `clave` | varchar(80) |  | no | Condición que la originó |
| `detalle` | jsonb |  | sí | Origen en palabras y sensores señalados |

Restricciones de unicidad:

- `(equipo_id, fuente, clave)` cuando `(fin IS NULL)`

Reglas de integridad (CHECK):

- `((((origen) <> 'modelo') OR (tipo_falla_id IS NOT NULL)))`
- `((((origen) <> 'regla') OR ((regla_id IS NOT NULL) AND (tipo_falla_id IS NULL))))`
- `(((fin IS NULL) OR (fin >= inicio)))`
- `(fuente IN ('real', 'simulado'))`
- `(origen IN ('regla', 'modelo'))`
- `(((reconocida_por IS NULL) = (reconocida_en IS NULL)))`
- `(severidad IN ('aviso', 'advertencia', 'critica'))`

## Mantenimiento

### `mantenimientos`

Bitácora de intervenciones de la planta. componente_id NULL = intervención de toda la línea (preventiva mensual)

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | integer | PK | no | Identificador |
| `equipo_id` | integer | FK → equipos | no | Equipo |
| `registrado_por` | integer | FK → usuarios | sí | Usuario que la registró (vacío si viene de la bitácora) |
| `tipo` | varchar(12) |  | no | preventivo, correctivo o predictivo |
| `alarma_id` | bigint | FK → alarmas | sí | Alarma que la originó, si la hubo |
| `fecha_inicio` | timestamptz |  | no | Inicio de la intervención |
| `fecha_fin` | timestamptz |  | sí | Término |
| `descripcion` | text |  | sí | Trabajo realizado |
| `fuente` | varchar(10) |  | no | simulado o real |
| `origen_registro` | varchar(10) |  | no | bitacora o dashboard |
| `componente_id` | smallint | FK → componentes | sí | Componente intervenido (vacío = toda la línea) |

Reglas de integridad (CHECK):

- `(((fecha_fin IS NULL) OR (fecha_fin >= fecha_inicio)))`
- `(fuente IN ('real', 'simulado'))`
- `(origen_registro IN ('bitacora', 'dashboard'))`
- `(tipo IN ('preventivo', 'correctivo', 'predictivo'))`

### `mantenimiento_fallas`

Modos de falla que atiende cada intervención: una correctiva atiende uno; una preventiva, varios

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `mantenimiento_id` | integer | PK, FK → mantenimientos | no | Intervención |
| `tipo_falla_id` | smallint | PK, FK → tipos_falla | no | Modo de falla que atendió |

## Usuarios y acceso

### `roles`

Roles del sistema: operador (nivel 2) y administrador (nivel 4)

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | smallint | PK | no | Identificador |
| `nombre` | varchar(30) | UQ | no | operador o administrador |
| `nivel` | smallint | UQ | no | 2 operador, 4 administrador |
| `descripcion` | varchar(200) |  | sí | Qué puede hacer |

Reglas de integridad (CHECK):

- `(((nivel >= 1) AND (nivel <= 4)))`
- `(nombre IN ('administrador', 'operador'))`

### `usuarios`

Usuarios del dashboard. Clave con bcrypt, bloqueo por intentos fallidos

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | integer | PK | no | Identificador |
| `rol_id` | smallint | FK → roles | no | Rol |
| `nombre` | varchar(120) |  | no | Nombre |
| `email` | varchar(150) |  | no | Correo (único, sin distinguir mayúsculas) |
| `password_hash` | varchar(255) |  | no | Clave cifrada con bcrypt |
| `activo` | boolean |  | no | Si puede ingresar |
| `debe_cambiar_clave` | boolean |  | no | Si tiene clave temporal |
| `intentos_fallidos` | smallint |  | no | Intentos fallidos seguidos |
| `bloqueado_hasta` | timestamptz |  | sí | Bloqueo temporal tras 5 intentos |
| `ultimo_acceso` | timestamptz |  | sí | Último ingreso |
| `creado_en` | timestamptz |  | no | Fecha de creación |

Restricciones de unicidad:

- `(lower((email)))`

### `auditoria_accesos`

Registro de ingresos y acciones administrativas

| Columna | Tipo | Clave | Nulo | Descripción |
|---|---|---|---|---|
| `id` | bigint | PK | no | Identificador |
| `usuario_id` | integer | FK → usuarios | sí | Usuario |
| `email` | varchar(150) |  | sí | Correo usado |
| `fecha` | timestamptz |  | no | Fecha y hora |
| `ip` | inet |  | sí | IP de origen |
| `accion` | varchar(50) |  | no | Acción (ingreso, cambio de rol…) |
| `detalle` | varchar(250) |  | sí | Detalle |
