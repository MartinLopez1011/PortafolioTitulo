# Backend – API de Mantenimiento Predictivo QLA

API REST en **FastAPI** que conecta la base de datos de Supabase (esquema `mantpred`) con la web del sistema.
Incluye inicio de sesión con 4 niveles de acceso y los datos que necesita el dashboard.

Responsable: Nicolás (Ingeniería de datos y backend)
Versión: 0.1.0 – octubre 2026

## Estructura

```
Backend/
├── app/
│   ├── main.py          # crea la API, CORS, manejo de errores y /api/salud
│   ├── config.py        # lee el archivo .env
│   ├── db.py            # pool de conexiones a PostgreSQL
│   ├── seguridad.py     # contraseñas (bcrypt), tokens (JWT), roles y auditoría
│   └── rutas/
│       ├── auth.py      # login, /me, cambio de contraseña
│       ├── usuarios.py  # gestión de usuarios y auditoría (solo administrador)
│       └── planta.py    # sensores, lecturas, estado, alarmas, predicciones, mantenimientos
├── requirements.txt
├── .env.example         # plantilla de configuración (copiar como .env)
└── .gitignore           # evita subir .env
```

## Cómo ejecutarlo (Windows)

```
cd "Fase 2/Evidencias Proyecto/Evidencia de sistema aplicacion/Backend"
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env          # completar DATABASE_URL y JWT_SECRET
python -m uvicorn app.main:app --reload
```

Abrir **http://127.0.0.1:8000/docs** para ver y probar todos los endpoints.

- `DATABASE_URL`: la misma cadena *Session pooler* de `Base de Datos/.env`.
- `JWT_SECRET`: clave aleatoria para firmar las sesiones. Generarla con
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## Roles

| Rol | Nivel | Puede |
| --- | --- | --- |
| visualizador | 1 | Ver dashboard, lecturas, alarmas, predicciones y mantenimientos |
| operador | 2 | Lo anterior + reconocer alarmas con comentario |
| supervisor | 3 | Lo anterior + registrar mantenimientos |
| administrador | 4 | Todo + crear, modificar y desbloquear usuarios; ver auditoría |

## Seguridad implementada

- Contraseñas guardadas con **bcrypt**; nunca en texto plano.
- Sesión con **token JWT** (HS256) que dura 8 horas (`JWT_MINUTOS`).
- **Cambio de contraseña obligatorio** en el primer ingreso: hasta hacerlo, solo funcionan `/auth/me` y `/auth/cambiar-clave`.
- Contraseñas nuevas de 8 a 72 caracteres, con letras y números.
- **Bloqueo de 15 minutos** tras 5 intentos fallidos. El administrador puede desbloquear asignando una clave temporal.
- Mensaje genérico ante error de login (no revela si el correo existe).
- Un usuario desactivado pierde el acceso de inmediato, aunque tenga un token vigente.
- **Auditoría**: cada login, intento fallido, bloqueo, cambio de clave y acción de administración queda en `auditoria_accesos`.
- CORS limitado a los orígenes de `CORS_ORIGINS`.
- Si Supabase está pausado o sin conexión, la API responde 503 con un mensaje claro y se recupera sola.

## Endpoints (prefijo `/api`)

| Método | Ruta | Rol mínimo | Para qué |
| --- | --- | --- | --- |
| GET | /salud | – | Estado de la API y de la base |
| POST | /auth/login | – | Iniciar sesión (correo y clave) |
| GET | /auth/me | con sesión | Datos del usuario |
| POST | /auth/cambiar-clave | con sesión | Cambiar la contraseña propia |
| GET | /resumen | visualizador | Indicadores del encabezado del dashboard |
| GET | /lecturas/ultimas | visualizador | Último valor de cada sensor (tarjetas) |
| GET | /lecturas/serie | visualizador | Serie de tiempo para gráficos (paso 1 min a 1 día) |
| GET | /estado/actual, /estado/historial | visualizador | Modo de operación y sus tramos |
| GET | /equipos, /sensores, /tipos-falla | visualizador | Catálogos |
| GET | /alarmas | visualizador | Alarmas activas o recientes |
| POST | /alarmas/{id}/reconocer | operador | Reconocer alarma con comentario |
| GET | /predicciones/ultimas | visualizador | Última predicción por modelo y horizonte |
| GET / POST | /mantenimientos | visualizador / supervisor | Ver y registrar mantenimientos |
| GET / POST / PATCH | /usuarios | administrador | Gestión de usuarios |
| POST | /usuarios/{id}/restablecer-clave | administrador | Clave temporal y desbloqueo |
| GET | /usuarios/auditoria | administrador | Registro de accesos |

Todas las consultas de datos aceptan `fuente=simulado` (por defecto) o `fuente=real`.

## Usuarios de prueba

Creados por `Base de Datos/bd_mantenimiento_predictivo_v2.sql` con la clave inicial `Qla.2026!`
(deben cambiarla al ingresar): `admin@demo.qla.cl`, `supervisor@demo.qla.cl`, `operador@demo.qla.cl`, `visor@demo.qla.cl`.
**Se eliminan antes de la entrega final.**

## Pruebas realizadas (11-10-2026, PostgreSQL 16 local con el mismo esquema)

- Login correcto, clave incorrecta, correo inexistente, usuario inactivo, token alterado y token expirado.
- Cambio de contraseña obligatorio, validación de clave débil y de clave actual incorrecta.
- Permisos: visualizador no reconoce alarmas (403), operador sí; operador no registra mantenimientos (403), supervisor sí; solo el administrador gestiona usuarios.
- Bloqueo al quinto intento fallido y desbloqueo por el administrador.
- Correo duplicado (409), rol inválido (422), administrador no puede desactivarse a sí mismo.
- Tiempos con 400 mil lecturas: últimas lecturas 47 ms, resumen 12 ms, serie de 4 sensores en 24 h 48 ms.
- Base detenida: responde 503 y se recupera sola al volver.
