# Evidencias del Proyecto - Mantenimiento Predictivo Industrial

Carpeta de evidencias del desarrollo e implementación del **Sistema de Mantenimiento Predictivo en la Industria** para Química Latinoamericana S.A. Contiene documentación técnica, código de aplicaciones, modelos de Machine Learning, configuración de infraestructura en AWS e información de campo.

---

## Estructura General

```
Evidencias Proyecto/
├── Evidencia de documentación/        (Documentos de análisis y planificación)
└── Evidencia de sistema aplicacion/   (Código, modelos e infraestructura)
```

---

## Evidencia de Documentación

Carpeta con documentos clave del proyecto generados durante la fase de planificación y análisis:

### Archivos Principales

| Archivo | Descripción |
|---------|-------------|
| **Especificación Técnica de Arquitectura.docx** | Documento detallado con el diseño de la arquitectura del sistema, componentes, integraciones y consideraciones técnicas |
| **Bitácora visita a terreno Quimica latinoamericana S.A #1.docx** | Registro de la primera visita al cliente incluyendo observaciones, requerimientos levantados y contexto operacional |
| **Resumen Ejecutivo Proyecto Mantenimiento Predictivo en la Industria.docx** | Documento ejecutivo con objetivos, alcance, impacto y propuesta de valor del proyecto |
| **Visita 01/** | Subcarpeta con evidencias fotográficas o adicionales de la visita a terreno |

---

## Evidencia de Sistema Aplicación

Carpeta principal con el código implementado, modelos de IA y configuración de infraestructura. Contiene 9 subcarpetas organizadas por componente:

### 1. **Backend**
**Ubicación:** `Evidencia de sistema aplicacion/Backend/`

Aplicación backend desarrollada con **FastAPI** que proporciona APIs REST/WebSocket, autenticación, control de simulación y los archivos estáticos de la web.

**Contenido principal:**
- `app/main.py` - Punto de entrada de la aplicación FastAPI
- `app/db.py` - Pool de conexiones a PostgreSQL (Amazon RDS / Supabase)
- `app/config.py` - Variables de configuración y validación de entorno
- `app/seguridad.py` - Módulo de autenticación con JWT, bcrypt, roles, ingesta y auditoría
- `app/catalogos.py` - Catálogo de equipos/componentes y consulta de intervenciones
- `app/persistencia.py` - Persistencia de inferencias y evaluación de alarmas
- `app/simulador.py` - Simulador controlable de planta hacia AWS IoT Core y DynamoDB
- `app/demo_store.py` - Almacenamiento y simulación en memoria para `MODO_DEMO=1`
- `app/rutas/` - Endpoints de la aplicación:
  - `auth.py` - Login, `/me`, cambio de contraseña
  - `planta.py` - Equipos, sensores, lecturas, alarmas, predicciones y mantenimientos
  - `pantallas.py` - Endpoints agregados de las vistas del dashboard
  - `ingesta.py` - `/ingesta/registro`, `/telemetria` y WebSocket `/ws/telemetria`
  - `simulacion.py` - Control del simulador (`HU-17` a `HU-19`)
  - `usuarios.py` - Gestión de usuarios y auditoría (administrador)
- `web/` - Interfaz web frontend:
  - `js/app.js`, `js/login.js`, `js/api.js`
  - `js/vendor/echarts.min.js` - Librería de gráficos Apache ECharts

**Características:**
- 2 roles de usuario: `administrador` y `operador`
- Autenticación JWT y auditoría de accesos
- Dashboard interactivo con diagrama P&ID y gráficos
- Canal WebSocket (`/api/ws/telemetria`) en tiempo real desde el backend + respaldo HTTP

---

### 2. **Base de Datos**
**Ubicación:** `Evidencia de sistema aplicacion/Base de Datos/`

Scripts y esquema PostgreSQL v4.1 (esquema `mantpred`) para **Amazon RDS (`qla-mantpred`, `us-east-2`)** o Supabase.

**Contenido principal:**
- `bd_mantpred_v4_1_completo.sql` - Esquema v4.1 completo en un solo archivo
- `bd_mantenimiento_predictivo_v2.sql` y migraciones `migracion_v3.sql`, `migracion_v4.sql`, `migracion_v4_1.sql` - Historial evolutivo del esquema
- `ejecutar_sql.py` - Ejecuta archivos `.sql` usando `DATABASE_URL`
- `crear_admin.py` - Crea o actualiza el usuario administrador real
- `cargar_datos.py` - Carga ventanas del dataset simulado en la BD
- `verificar_bd.py` - Verificación rápida de tablas y últimos registros
- `DICCIONARIO_DATOS.md` y `README.md` - Documentación del esquema de 16 tablas

**Funcionalidad:**
- Gestión centralizada de datos operacionales y series temporales
- Histórico de mediciones, predicciones y condiciones por minuto
- Registro de alarmas generadas por reglas o modelos
- Trazabilidad de mantenimiento realizado

---

### 3. **Modelo 1 - Diagnóstico**
**Ubicación:** `Evidencia de sistema aplicacion/Modelo 1 - Diagnóstico/`

Notebook Jupyter: `Modelos_Fallas_Molino_QLA.ipynb`

**Propósito:** Clasificar el estado actual del equipo (molino) identificando qué tipo de falla está presentando.

**Contenido:**
- Carga y exploración de datos históricos
- Feature engineering sobre las 31 variables de entrada
- Entrenamiento de modelos de clasificación y comparación de métricas
- Validación (precisión, recall, F1-score) y serialización del modelo entrenado

**Salida:** Modelo que clasifica la condición/falla presente en el molino en tiempo real

---

### 4. **Modelo 2 - Vigilancia**
**Ubicación:** `Evidencia de sistema aplicacion/Modelo 2 - Vigilancia/`

Notebook Jupyter: `Autoencoder_Molino_QLA.ipynb`

**Propósito:** Detectar anomalías no previstas mediante aprendizaje no supervisado.

**Contenido:**
- Arquitectura de Autoencoder (red neuronal Keras)
- Entrenamiento con operación normal del molino
- Cálculo de umbral de error de reconstrucción
- Detección y trazabilidad de anomalías en series temporales

**Salida:** Modelo de detección de comportamientos anómalos en el equipo

---

### 5. **Modelo 3 - Predicción**
**Ubicación:** `Evidencia de sistema aplicacion/Modelo 3 - Predicción/`

Notebook Jupyter: `Prediccion_Fallas_Molino_QLA.ipynb`

**Propósito:** Predecir fallas futuras con horizonte temporal de anticipación sobre ventana móvil de 168 h.

**Contenido:**
- Preparación de series temporales e ingeniería de features temporales y de bitácora
- Entrenamiento de modelos predictivos multi-horizonte (`LightGBM`)
- Definición de umbrales de riesgo y métricas de desempeño
- Exportación de artefactos para inferencia en Lambda

**Salida:** Modelo que anticipa la probabilidad de falla por horizonte temporal

---

### 6. **Edge Gateway**
**Ubicación:** `Evidencia de sistema aplicacion/edge_gateway/`

Simulador de dispositivo Edge (`simulador_edge.py`) que envía lecturas de sensores a la URL de inferencia configurada en `LAMBDA_URL`.

---

### 7. **Infraestructura AWS**
**Ubicación:** `Evidencia de sistema aplicacion/infraestructura_aws/`

Configuración, scripts IaC (Linux y PowerShell) y flujos CI/CD en AWS (`us-east-2`).

**Contenido principal:**
- `desplegar_infraestructura_aws.sh` / `.ps1` - Despliegue dual (`lab` y `prod`) de S3, Glue, Firehose, Athena, DynamoDB, Lambda e IoT Core
- `setup_iam_prod.sh` / `.ps1` - Provisionamiento de roles IAM *least-privilege* para modo `prod`
- `build_and_push_ecr.sh` / `.ps1` - Construcción y publicación de la imagen Lambda en ECR
- `desplegar_dashboard_aws.ps1`, `crear_rds.ps1`, `conectar_servidor_rds.ps1` - Provisionamiento y conexión de EC2, API Gateway, RDS y `qla-persistencia`
- `lambda_persistencia/lambda_function.py` - Lambda que reenvía registros del Stream de DynamoDB hacia el Backend
- `cicd/` - Scripts de despliegue automatizado vía GitHub Actions (`setup_github_oidc.sh`, `github_deploy_policy.json`, `ensure_ec2_and_apigw.sh`, `deploy_backend_ec2.sh`)
- `probar_arquitectura_completa.py` y `simular_telemetria_continua.py` - Validación extremo a extremo y simulación continua
- Plantillas JSON: `iot_policy_updated.json`, `iot_rule_firehose.json`, `firehose_update.json`, `glue_table.json`, `glue_database.json`
- Documentación: `ARQUITECTURA_DUAL_Y_COSTOS_AWS.md` y `GUIA_DESPLIEGUE_DASHBOARD.md`

**Servicios AWS utilizados:**
- **AWS IoT Core:** Ingesta MQTT y motor de reglas
- **Amazon Data Firehose + S3:** Almacenamiento histórico en Parquet
- **AWS Glue + Athena:** Catálogo y consultas analíticas sobre Data Lake
- **ECR + AWS Lambda:** Inferencia ML contenerizada y persistencia serverless
- **Amazon DynamoDB:** Estado reciente y buffer de resultados
- **EC2 + API Gateway HTTP + SSM + RDS PostgreSQL:** Hospedaje del backend/dashboard y base operacional

---

### 8. **Lambda Inferencia**
**Ubicación:** `Evidencia de sistema aplicacion/lambda_inferencia/`

Función Lambda AWS contenerizada para ejecutar los 3 modelos en tiempo real sobre telemetría del molino.

**Contenido principal:**
- `app/lambda_function.py` - Handler de la Lambda (DynamoDB, ventana 168 h en S3 con bloqueo optimista, publicación IoT Core y HTTP)
- `app/inference_engine.py` - Motor de inferencia (`31 -> 11 -> 80` y evaluación conjunta de los 3 modelos)
- `app/config.py` - Configuración y rutas de artefactos
- `artifacts/` - Modelos serializados (`.joblib`, `.keras`)
- `Dockerfile`, `requirements.txt`, `tests/`

---

### 9. **Dataset Simulado**
**Ubicación:** `Evidencia de sistema aplicacion/Dataset Simulado/`

Datos sintéticos realistas generados para entrenar, validar y reproducir el comportamiento anual del molino (`Dataset_Molino_QLA_Realista.zip`).

---

## Arquitectura General

```
Sensores / Simulador
        ↓ MQTT
AWS IoT Core
   ├──► Kinesis Data Firehose ──► S3 Data Lake (Parquet) ──► Glue / Athena
   └──► Lambda Inferencia (Modelos ML) ──► DynamoDB
                                                │ (Stream / Recolector)
                                                ▼
Navegador (Dashboard JS + WS) ◄── API Gateway / EC2 (Backend FastAPI) ──► Amazon RDS (PostgreSQL)
```

---

## Cómo Usar

### Para explorar la documentación:
```
1. Revisar: Evidencia de documentación/*.docx
2. Especialmente: "Especificación Técnica de Arquitectura.docx"
```

### Para ejecutar el backend:
```bash
cd "Evidencia de sistema aplicacion/Backend"
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload
```

### Para configurar y poblar la base de datos:
```bash
cd "Evidencia de sistema aplicacion/Base de Datos"
python ejecutar_sql.py bd_mantpred_v4_1_completo.sql --env "$HOME/qla_rds.env"
python crear_admin.py --env "$HOME/qla_rds.env"
python cargar_datos.py --csv "../Dataset Simulado/Dataset_Molino_QLA_Realista.zip"
```

### Para entrenar modelos:
```
Abrir los Jupyter Notebooks:
- Modelo 1 - Diagnóstico/*.ipynb
- Modelo 2 - Vigilancia/*.ipynb
- Modelo 3 - Predicción/*.ipynb
```

### Para desplegar o validar en AWS:
```bash
cd "Evidencia de sistema aplicacion/infraestructura_aws"
./desplegar_infraestructura_aws.sh prod
python probar_arquitectura_completa.py
```

---

## Notas Importantes

- **Seguridad:** Nunca subir archivos `.env`, credenciales `~/.aws/credentials`, llaves ni certificados al repositorio.
- **Variables de entorno:** Usar plantillas `.env.example` o configurar `secrets` / `vars` de GitHub Actions para CI/CD.
- **Modelos:** Los artefactos entrenados viven en `lambda_inferencia/artifacts/` (`.joblib` y `.keras`).
- **Base de datos:** Usa PostgreSQL en Amazon RDS (`qla-mantpred`, región `us-east-2`) o Supabase compatible; también soporta `MODO_DEMO=1` sin base de datos.
- **Simuladores:** El simulador integrado del dashboard y `simular_telemetria_continua.py` permiten probar el flujo completo sin conexión física a planta.

---

## Contacto & Soporte

Para preguntas sobre estructura o contenido, revisar documentos en `Evidencia de documentación/` o contactar al equipo de desarrollo.

**Equipo:**
- Franco Carvajal
- Martín López
- Nicolás Tapia
