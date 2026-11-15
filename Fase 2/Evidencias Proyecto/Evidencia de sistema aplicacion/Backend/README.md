# Backend – API de Mantenimiento Predictivo QLA

API REST y WebSocket en **FastAPI** que conecta la base PostgreSQL (Amazon RDS / Supabase, esquema `mantpred`) con la web del sistema,
servida como archivos estáticos desde la misma API. Incluye autenticación JWT con **2 roles de acceso** (`operador` y `administrador`)
y un modo de demostración en memoria (`MODO_DEMO=1`).

## Estructura

```
Backend/
├── app/
│   ├── main.py          # crea la API, CORS, sin caché en estáticos, errores y /api/salud
│   ├── config.py        # lee el archivo .env y valida variables obligatorias
│   ├── db.py            # pool de conexiones a PostgreSQL
│   ├── seguridad.py     # contraseñas (bcrypt), tokens (JWT), roles, ingesta y auditoría
│   ├── catalogos.py     # equipos/componentes y consulta común de última intervención
│   ├── persistencia.py  # inserción de lecturas/predicciones y evaluación de reglas de alarma
│   ├── simulador.py     # simulador controlable del año 2026 hacia IoT Core y DynamoDB
│   ├── demo_store.py    # datos y simulación en memoria para MODO_DEMO=1
│   └── rutas/
│       ├── auth.py      # login, /me, cambio de contraseña
│       ├── usuarios.py  # gestión de usuarios y auditoría (solo administrador)
│       ├── planta.py    # equipos, sensores, lecturas, estado, alarmas, predicciones y mantenimientos
│       ├── pantallas.py # respuestas agregadas para Proceso, Predicción, Alarmas, Salud y Mantenimiento
│       ├── ingesta.py   # /ingesta/registro, /telemetria y WebSocket /ws/telemetria
│       └── simulacion.py# control del simulador (HU-17 a HU-19)
├── web/                 # login y dashboard (HTML, CSS y JavaScript sin compilación)
│   ├── login.html, index.html
│   ├── css/app.css
│   ├── js/api.js, js/login.js, js/app.js
│   ├── js/vendor/echarts.min.js   # gráficos (Apache ECharts 5.5.1, licencia Apache 2.0)
│   └── img/logo-qla.png
├── tests/               # pruebas unitarias y de rutas (pytest)
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── ruff.toml
└── .env.example         # plantilla de configuración (copiar como .env)
```

*(El `.gitignore` del repositorio evita subir archivos `.env` y cachés).*

## Cómo ejecutarlo

**Linux / macOS:**

```bash
cd "Fase 2/Evidencias Proyecto/Evidencia de sistema aplicacion/Backend"
python -m pip install -r requirements.txt
cp .env.example .env
# Completar JWT_SECRET (y DATABASE_URL + CLAVE_INGESTA, o MODO_DEMO=1 + DEMO_CLAVE)
python -m uvicorn app.main:app --reload
```

**Windows (PowerShell):**

```powershell
cd "Fase 2\Evidencias Proyecto\Evidencia de sistema aplicacion\Backend"
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python -m uvicorn app.main:app --reload
```

- **Web del sistema:** http://127.0.0.1:8000
- **Documentación de la API:** http://127.0.0.1:8000/docs

Variables clave en `.env`:
- `DATABASE_URL`: cadena de conexión a Amazon RDS o Supabase (no requerida si `MODO_DEMO=1`).
- `JWT_SECRET`: clave aleatoria (>= 32 caracteres) para firmar las sesiones:
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `CLAVE_INGESTA`: clave compartida (>= 24 caracteres) exigida en `X-Clave-Ingesta` por `/api/ingesta/registro` y `/api/telemetria`.
- `MODO_DEMO` / `DEMO_CLAVE`: `MODO_DEMO=1` arranca sin PostgreSQL usando datos de demostración en memoria (`DEMO_CLAVE` >= 8 caracteres).

## La web

| Pestaña | Qué muestra | Quién la ve |
| --- | --- | --- |
| Proceso | Diagrama P&ID interactivo, estado del molino, medidores, tendencias, diagnóstico actual, alarmas activas, riesgo de falla e indicadores del día | Todos |
| Predicción | Semáforo de riesgo por falla y horizonte + evolución del riesgo (`HU-14`) | Todos |
| Alarmas | Alarmas activas e historial; botón para reconocer con comentario | Todos |
| Salud del equipo | Error medio diario de reconstrucción del autoencoder y trazabilidad de anomalías | Todos |
| Mantenimiento | Estado por equipo, bitácora y formulario para registrar intervenciones | Todos |
| Simulación (demo) | Controles de reproducción, saltos a fallas e inyección de escenarios 2026 (`HU-17` a `HU-19`) | Todos |
| Usuarios | Crear, modificar o eliminar usuarios, asignar contraseñas temporales y ver auditoría de accesos | Administrador |

- En el primer ingreso (o tras una contraseña temporal) la web exige crear una contraseña nueva.
- El selector de fuente permite alternar entre datos **simulados** y **reales**.
- La actualización en vivo usa WebSocket (`WS /api/ws/telemetria`) cuando está disponible y respaldo por sondeo HTTP.
- La sesión se guarda en `sessionStorage` de la pestaña del navegador.

## Roles

| Rol | Nivel | Puede |
| --- | --- | --- |
| operador | 2 | Ver todas las vistas de planta/modelos, reconocer alarmas, registrar mantenimientos y operar el simulador |
| administrador | 4 | Todo lo del operador + crear, editar, eliminar y restablecer usuarios; ver auditoría |

## Seguridad implementada

- Contraseñas guardadas con **bcrypt**; nunca en texto plano ni devueltas por la API.
- Sesión con **token JWT** (HS256) de 8 horas por defecto (`JWT_MINUTOS`).
- **Cambio de contraseña obligatorio** en el primer ingreso o tras un restablecimiento temporal.
- Contraseñas nuevas de 8 a 72 caracteres, con letras y números.
- **Bloqueo temporal** de `MINUTOS_BLOQUEO` (15 min) tras `MAX_INTENTOS` (5) fallidos; el administrador puede desbloquear con clave temporal.
- Mensaje genérico y verificación constante ante errores de login.
- Un usuario desactivado pierde el acceso en la siguiente petición, aunque conserve un JWT vigente.
- **Auditoría**: accesos, intentos fallidos, bloqueos, cambios de clave y acciones administrativas quedan en `auditoria_accesos`.
- Ingesta protegida mediante comparación en tiempo constante (`hmac.compare_digest`) sobre `X-Clave-Ingesta`.
- CORS limitado a los orígenes configurados en `CORS_ORIGINS`.
- Si PostgreSQL no responde, la API responde `503` y se recupera sola cuando la base vuelve.

## Endpoints (prefijo `/api`)

| Método | Ruta | Acceso / Rol mínimo | Para qué |
| --- | --- | --- | --- |
| GET | /salud | público | Estado de la API y conexión a base de datos |
| POST | /auth/login | público | Iniciar sesión y obtener JWT |
| GET | /auth/me | con sesión | Datos del usuario autenticado |
| POST | /auth/cambiar-clave | con sesión | Cambiar contraseña propia |
| GET | /proceso, /prediccion, /prediccion/evolucion | operador | Datos agregados para Proceso y Predicción |
| GET | /alarmas/pantalla, /salud-equipo, /mantenimiento/pantalla | operador | Vistas de Alarmas, Salud y Mantenimiento |
| GET | /resumen | operador | Indicadores del encabezado del dashboard |
| GET | /lecturas/ultimas, /lecturas/serie | operador | Últimas lecturas y series temporales |
| GET | /estado/actual, /estado/historial | operador | Modo de operación y sus tramos |
| GET | /equipos, /sensores, /tipos-falla | operador | Catálogos |
| GET | /alarmas | operador | Alarmas activas o recientes |
| POST | /alarmas/{id}/reconocer | operador | Reconocer alarma con comentario |
| GET | /predicciones/ultimas | operador | Última predicción por modelo y horizonte |
| GET / POST | /mantenimientos | operador | Ver y registrar mantenimientos |
| GET / POST | /simulacion, /simulacion/opciones | operador | Consultar y controlar el simulador |
| POST | /ingesta/registro, /telemetria | `X-Clave-Ingesta` | Recibir inferencias o telemetría en vivo desde AWS |
| WS | /ws/telemetria?token=... | con sesión (JWT) | Canal WebSocket hacia los navegadores |
| GET / POST / PATCH / DELETE | /usuarios | administrador | Gestión de usuarios |
| POST | /usuarios/{id}/restablecer-clave | administrador | Clave temporal y desbloqueo |
| GET | /usuarios/auditoria | administrador | Registro de accesos |

Las consultas operacionales aceptan `fuente=simulado` (por defecto) o `fuente=real`.

## Usuarios de prueba

- En `MODO_DEMO=1`: existen `admin@demo.qla.cl` (`administrador`) y `operador@demo.qla.cl` (`operador`) con la contraseña definida en `DEMO_CLAVE`.
- En base de datos real: los usuarios `@demo.qla.cl` se desactivan o eliminan antes de producción y se crea el administrador real con `Base de Datos/crear_admin.py`.

## Pruebas automatizadas

La suite de pruebas unitarias y de rutas vive en [`tests/`](tests) y se ejecuta en CI (`.github/workflows/ci.yml`) o localmente:

```bash
pip install -r requirements-dev.txt
ruff check app tests && pytest --cov=app
```
