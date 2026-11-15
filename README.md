# Sistema de Mantenimiento Predictivo Industrial con IA e IoT

Sistema integral de telemetría, monitoreo en tiempo real y mantenimiento predictivo basado en Machine Learning e Internet de las Cosas (IoT), aplicado al **Molino Coloidal MC-01** en la planta de emulsiones asfálticas de **Química Latinoamericana S.A.** (Industria 4.0).

Su propósito es anticipar fallas operacionales y fallas de instrumentación, detectar anomalías tempranas mediante modelos no supervisados y asistir la toma de decisiones operacionales desde un dashboard web interactivo.

---

## 👥 Integrantes del Proyecto

- **Franco Carvajal**
- **Martín López**
- **Nicolás Tapia**

**Empresa Colaboradora:** Química Latinoamericana S.A. (Sector de emulsiones asfálticas).

---

## 🎯 Objetivos e Impacto

- **Económico:** Reducir costos por detenciones no planificadas y optimizar intervenciones de mantenimiento.
- **Operacional:** Incrementar la disponibilidad del molino MC-01 y equipos asociados mediante diagnóstico y predicción multi-horizonte.
- **Social / Seguridad:** Mejorar la seguridad operacional entregando alertas tempranas fundamentadas a operadores e ingenieros.
- **Tecnológico:** Integrar telemetría IoT, almacenamiento analítico en la nube, inferencia serverless de 3 modelos ML y despliegue automatizado CI/CD en AWS (`us-east-2`).

---

## 🏗️ Arquitectura General (`us-east-2`)

El sistema opera sobre tres rutas de datos paralelas alimentadas por el contrato canónico de **31 variables**:

```
Sensores / Simulador MC-01
        │
        ▼ MQTT
  AWS IoT Core
   ├──► [Cold Path]  Amazon Data Firehose ──► S3 Data Lake (Parquet) ──► Glue / Athena
   └──► [ML Path]    Lambda qla-molino-inferencia (3 modelos + ventana 168 h en S3) ──► DynamoDB
                                                                                            │
                                                                    (Stream / Recolector) ◄─┘
                                                                          │
                                                                          ▼
  Navegador (Dashboard + WS) ◄── API Gateway ── EC2 qla-servidor (FastAPI) ──► Amazon RDS PostgreSQL
```

1. **Diagnóstico (Clasificación supervisada):** identifica la falla o condición presente en el minuto actual.
2. **Vigilancia (Autoencoder Keras):** detecta desviaciones multivariantes no vistas frente a operación normal.
3. **Predicción (LightGBM multi-horizonte):** estima probabilidad de falla futura y días estimados a partir de una ventana móvil de 168 horas y estado de bitácora.

---

## 📂 Estructura del Repositorio

- **[`Fase 1/`](Fase%201):** Planificación, definición del proyecto (`1.5_GuiaEstudiante_Fase 1_*`), autoevaluaciones y [`Presentacion_Fase_1.pdf`](Fase%201/Evidencias%20Grupales/Presentacion_Fase_1.pdf).
- **[`Fase 2/`](Fase%202):**
  - **[`Evidencias Proyecto/Evidencia de documentación/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20documentaci%C3%B3n):** Acta de constitución, bitácora de visita a terreno, especificación técnica de arquitectura, diagramas y resumen ejecutivo.
  - **[`Evidencias Proyecto/Evidencia de sistema aplicacion/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion)** *(ver [README técnico](Fase%202/Evidencias%20Proyecto/README.md))*:
    - [`Backend/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Backend/README.md) — API REST/WebSocket en FastAPI, autenticación JWT (2 roles: `operador`, `administrador`), simulador 2026 integrado, pruebas `pytest` y frontend estático (P&ID SVG + Apache ECharts).
    - [`Base de Datos/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Base%20de%20Datos/README.md) — Esquema PostgreSQL v4.1 (`mantpred`, 16 tablas, `bd_mantpred_v4_1_completo.sql`), [diccionario de datos](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Base%20de%20Datos/DICCIONARIO_DATOS.md) y scripts CLI (`ejecutar_sql.py`, `crear_admin.py`, `cargar_datos.py`, `verificar_bd.py`).
    - [`lambda_inferencia/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/lambda_inferencia) — Imagen Docker AWS Lambda con el motor [`inference_engine.py`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/lambda_inferencia/app/inference_engine.py), artefactos entrenados (`.joblib`, `.keras`) y suite de pruebas.
    - [`Modelo 1 - Diagnóstico/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Modelo%201%20-%20Diagn%C3%B3stico), [`Modelo 2 - Vigilancia/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Modelo%202%20-%20Vigilancia) y [`Modelo 3 - Predicción/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Modelo%203%20-%20Predicci%C3%B3n) — Notebooks de entrenamiento y evaluación.
    - [`infraestructura_aws/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/infraestructura_aws) — Scripts duales (`lab` / `prod`) en Bash y PowerShell, roles IAM *least-privilege*, Lambda `qla-persistencia` y scripts `cicd/` para EC2/SSM/API Gateway.
    - [`edge_gateway/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/edge_gateway) y [`Dataset Simulado/`](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Dataset%20Simulado) — Simulador Edge y dataset anual (`Dataset_Molino_QLA_Realista.zip`).
- **[`docs/`](docs)** y **[`.github/workflows/`](.github/workflows):** Guía [`CICD.md`](docs/CICD.md), gráficos KPI en [`docs/graficos_kpis/`](docs/graficos_kpis) y pipelines de CI (`ci.yml`), despliegue manual (`cd.yml`) y control de encendido/apagado AWS (`control_aws.yml`).
- **Fase 3 (Evaluación y Cierre):** Validación técnica, pruebas operacionales y cierre formal del proyecto de título.

---

## 🛠️ Stack Tecnológico

- **Backend & Frontend:** Python 3.12, FastAPI, Uvicorn, PostgreSQL (`psycopg`), JWT, bcrypt, HTML/CSS/JavaScript, Apache ECharts.
- **Machine Learning & Datos:** scikit-learn, LightGBM, TensorFlow/Keras, pandas, NumPy, pyarrow, joblib.
- **Nube AWS (`us-east-2`):** IoT Core, Data Firehose, S3, Glue, Athena, DynamoDB, Lambda (ECR Container), EC2, API Gateway HTTP, Systems Manager (SSM), RDS PostgreSQL.
- **Calidad & CI/CD:** Docker, GitHub Actions (OIDC / IAM), `ruff`, `shellcheck`, `pytest`.

---

## 🚀 Inicio Rápido (Modo Demo Local sin BD)

Para levantar el backend y el dashboard localmente con datos en memoria:

```bash
cd "Fase 2/Evidencias Proyecto/Evidencia de sistema aplicacion/Backend"
docker build -t qla-backend:local .
docker run --rm -p 8000:8000 \
  -e MODO_DEMO=1 -e DEMO_CLAVE=ClaveDemo2026 \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  qla-backend:local
```

Luego abrir `http://127.0.0.1:8000` (credenciales demo: `admin@demo.qla.cl` / `ClaveDemo2026`).

---

## 📚 Documentación Detallada

- [Arquitectura e índice del Sistema Aplicación](Fase%202/Evidencias%20Proyecto/README.md)
- [Backend API y Dashboard Web](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Backend/README.md)
- [Base de Datos PostgreSQL v4.1](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/Base%20de%20Datos/README.md)
- [CI/CD con Docker, GitHub Actions y AWS](docs/CICD.md)
- [Arquitectura Dual (Lab vs. Prod) y Costos AWS](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/infraestructura_aws/ARQUITECTURA_DUAL_Y_COSTOS_AWS.md)
- [Guía de Despliegue del Dashboard en AWS](Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/infraestructura_aws/GUIA_DESPLIEGUE_DASHBOARD.md)