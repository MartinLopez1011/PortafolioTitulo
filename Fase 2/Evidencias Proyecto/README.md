# 📚 Evidencias del Proyecto - Mantenimiento Predictivo Industrial

Carpeta de evidencias del desarrollo e implementación del **Sistema de Mantenimiento Predictivo en la Industria** para Química Latinoamericana S.A. Contiene documentación técnica, código de aplicaciones, modelos de Machine Learning, configuración de infraestructura en AWS e información de campo.

---

## 📂 Estructura General

```
Evidencias Proyecto/
├── Evidencia de documentación/        (Documentos de análisis y planificación)
└── Evidencia de sistema aplicacion/   (Código, modelos e infraestructura)
```

---

## 📄 Evidencia de Documentación

Carpeta con documentos clave del proyecto generados durante la fase de planificación y análisis:

### Archivos Principales

| Archivo | Descripción |
|---------|-------------|
| **Especificación Técnica de Arquitectura.docx** | Documento detallado con el diseño de la arquitectura del sistema, componentes, integraciones y consideraciones técnicas |
| **Bitácora visita a terreno Quimica latinoamericana S.A #1.docx** | Registro de la primera visita al cliente incluyendo observaciones, requerimientos levantados y contexto operacional |
| **Resumen Ejecutivo Proyecto Mantenimiento Predictivo en la Industria.docx** | Documento ejecutivo con objetivos, alcance, impacto y propuesta de valor del proyecto |
| **Visita 01/** | Subcarpeta con evidencias fotográficas o adicionales de la visita a terreno |

---

## 💻 Evidencia de Sistema Aplicación

Carpeta principal con el código implementado, modelos de IA y configuración de infraestructura. Contiene 11 subcarpetas organizadas por componente:

### 1. 🔌 **Backend**
**Ubicación:** `Evidencia de sistema aplicacion/Backend/`

Aplicación backend desarrollada con **FastAPI** que proporciona APIs REST, autenticación y gestión de datos.

**Contenido principal:**
- `app/main.py` - Punto de entrada de la aplicación FastAPI
- `app/db.py` - Configuración y modelos de base de datos (Supabase)
- `app/config.py` - Variables de configuración y variables de entorno
- `app/seguridad.py` - Módulo de autenticación con JWT y roles
- `app/rutas/` - Endpoints de la aplicación:
  - `auth.py` - Login, logout, validación de tokens
  - `planta.py` - Datos de equipos, sensores y telemetría (NUEVO)
  - `usuarios.py` - Gestión de usuarios con roles
- `web/` - Interfaz web frontend:
  - `js/app.js` - Lógica principal de la aplicación
  - `js/login.js` - Manejo del formulario de login
  - `js/api.js` - Cliente HTTP para comunicación con backend
  - `js/vendor/` - Librerías externas (ECharts, Paho MQTT)

**Características:**
- 4 roles de usuario: admin, supervisor, operador, visor
- Autenticación JWT
- Dashboard interactivo con gráficos
- Conexión WebSocket para telemetría en tiempo real
- Integración MQTT para datos de IoT

---

### 2. 🗄️ **Base de Datos**
**Ubicación:** `Evidencia de sistema aplicacion/Base de Datos/`

Scripts y esquema de la base de datos en **Supabase** (PostgreSQL).

**Contenido principal:**
- `bd_mantenimiento_predictivo_v2.sql` - Schema completo con tablas de:
  - Usuarios y roles
  - Equipos (molinos, bombas, etc.)
  - Sensores y mediciones
  - Alertas y mantenimiento
  - Logs operacionales
- `cargar_datos.py` - Script Python que carga datos simulados en la BD
- `.env.example` - Template de variables de entorno (credenciales Supabase)
- `README.md` - Instrucciones para configurar la BD

**Funcionalidad:**
- Gestión centralizada de datos operacionales
- Histórico de mediciones de sensores
- Registro de alertas generadas por modelos predictivos
- Trazabilidad de mantenimiento realizado

---

### 3. 🤖 **Modelo 1 - Diagnóstico**
**Ubicación:** `Evidencia de sistema aplicacion/Modelo 1 - Diagnóstico/`

Notebook Jupyter: `Modelos_Fallas_Molino_QLA.ipynb`

**Propósito:** Clasificar el estado actual del equipo (molino) identificando qué tipo de falla está presentando.

**Contenido:**
- Carga y exploración de datos históricos
- Feature engineering de series temporales
- Entrenamiento de modelos de clasificación (Random Forest, SVM, etc.)
- Validación con métricas (precisión, recall, F1-score)
- Serialización del modelo entrenado

**Salida:** Modelo que predice la clase de falla presente en el molino en tiempo actual

---

### 4. 📊 **Modelo 2 - Vigilancia**
**Ubicación:** `Evidencia de sistema aplicacion/Modelo 2 - Vigilancia/`

Notebook Jupyter: `Autoencoder_Molino_QLA.ipynb`

**Propósito:** Detectar anomalías no previstas mediante aprendizaje no supervisado.

**Contenido:**
- Arquitectura de Autoencoder (red neuronal)
- Entrenamiento con datos normales del molino
- Cálculo de umbral de reconstrucción
- Detección de outliers comparando error de reconstrucción
- Visualización de anomalías en series temporales

**Salida:** Modelo de detección de comportamientos anómalos en el equipo

---

### 5. 🔮 **Modelo 3 - Predicción**
**Ubicación:** `Evidencia de sistema aplicacion/Modelo 3 - Predicción/`

Notebook Jupyter: `Prediccion_Fallas_Molino_QLA.ipynb`

**Propósito:** Predecir fallas futuras con horizonte temporal de anticipación.

**Contenido:**
- Preparación de series temporales con ventanas temporales
- Modelos LSTM, ARIMA o Prophet para pronóstico
- Definición de umbrales de alerta
- Métricas de desempeño predictivo
- Exportación de modelos para inferencia en tiempo real

**Salida:** Modelo que anticipa cuándo ocurrirá una falla en los próximos días/horas

---

### 6. 📡 **Edge Gateway**
**Ubicación:** `Evidencia de sistema aplicacion/edge_gateway/`

Simulador de dispositivo IoT edge que envía datos de sensores a AWS.

**Contenido principal:**
- `certs/simulador_edge.py` - Script que:
  - Simula lectura de sensores (temperatura, vibración, presión, etc.)
  - Conecta con AWS IoT Core usando credenciales
  - Publica datos en tópicos MQTT
  - Genera telemetría realista del molino
- `certs/` - Certificados y claves para autenticación en AWS IoT

**Funcionalidad:**
- Genera datos sintéticos realistas para pruebas
- Simula múltiples equipos en paralelo
- Integración con infraestructura AWS

---

### 7. ☁️ **Infraestructura AWS**
**Ubicación:** `Evidencia de sistema aplicacion/infraestructura_aws/`

Configuración, scripts y documentación de la arquitectura en AWS.

**Contenido principal:**
- `probar_arquitectura_completa.py` - Script para validar toda la pipeline AWS:
  - Conexión con AWS IoT Core
  - Lectura de datos desde Kinesis Firehose
  - Almacenamiento en S3
  - Procesamiento con AWS Glue
- `simular_telemetria_continua.py` - Simulador contínuo de datos de sensores
- `test_iot_ws_signer.py` - Tester para validar la firma WebSocket en IoT
- Configuración JSON de servicios AWS:
  - `iot_policy_updated.json` - Política de permisos IoT
  - `iot_rule_firehose.json` - Regla para enviar datos a Firehose
  - `firehose_update.json` - Configuración de Kinesis Firehose
  - `glue_table.json` / `glue_database.json` - Metadatos para AWS Glue
  - `iam_policies.json` - Políticas IAM de acceso
- `build_and_push_ecr.ps1` - Script PowerShell para construir imagen Docker y subirla a ECR
- `example.md` - Documentación con ejemplos de uso

**Servicios AWS utilizados:**
- **AWS IoT Core:** Conexión segura de dispositivos
- **Kinesis Firehose:** Ingesta de datos en tiempo real
- **S3:** Almacenamiento de datos históricos
- **AWS Glue:** Procesamiento ETL
- **ECR:** Registro de contenedores Docker
- **Lambda:** Funciones serverless para inferencia

---

### 8. 🚀 **Lambda Inferencia**
**Ubicación:** `Evidencia de sistema aplicacion/lambda_inferencia/`

Función Lambda AWS para ejecutar los modelos predictivos en tiempo real sobre datos nuevos.

**Contenido principal:**
- `app/lambda_function.py` - Punto de entrada de la función Lambda:
  - Lee datos desde eventos de AWS
  - Carga modelos entrenados
  - Ejecuta inferencia
  - Retorna predicciones
- `app/inference_engine.py` - Motor de inferencia:
  - Cargador de modelos
  - Preprocesamiento de features
  - Ejecución de clasificación, detección y predicción
- `app/config.py` - Variables de configuración
- `artifacts/` - Modelos serializados (.pkl, .h5)

**Funcionalidad:**
- Procesamiento sin servidor (serverless)
- Escalado automático según demanda
- Integración con IoT Core y Firehose
- API HTTP mediante Function URL

---

### 9. 📈 **Ejemplo Dashboard Simulado**
**Ubicación:** `Evidencia de sistema aplicacion/ejemplo dashboard simulado/`

Prototipo de dashboard interactivo con datos simulados.

**Contenido principal:**
- `qla_dashboard_predictivo/` - Aplicación Flask:
  - `app.py` - Servidor Flask principal
  - `config.py` - Configuración
  - `modelos.py` - Carga y ejecuta modelos predictivos
  - `fuentes.py` - Generador de datos simulados
  - `escenarios.py` - Define escenarios de simulación
  - `predictivo.py` - Lógica de predicción
  - `registro.py` - Logging y trazabilidad
  - `static/` - Assets HTML, CSS, JavaScript
- Interfaz para visualizar:
  - Panel de estado actual de equipos
  - Tendencias históricas
  - Alertas generadas
  - Predicciones futuras

**Características:**
- Simulación en tiempo real
- Gráficos interactivos
- Dashboard responsivo
- Datos sintéticos para testing

---

### 10. 📊 **Dataset Simulado**
**Ubicación:** `Evidencia de sistema aplicacion/Dataset Simulado/`

Datos sintéticos generados para entrenar y validar los modelos.

**Contenido:**
- Series temporales de sensores (temperatura, vibración, presión, etc.)
- Etiquetas de fallas conocidas para entrenar Modelo 1
- Datos normales para entrenar Modelo 2 (Autoencoder)
- Secuencias temporales para entrenar Modelo 3
- Formato: CSV, JSON o Parquet

**Propósito:**
- Permite desarrollar sin acceso a datos reales del cliente
- Simula comportamientos realistas del molino
- Base para validar modelos antes de desplegar

---

## 🔗 Arquitectura General

```
Sensores (Molino)
        ↓
Edge Gateway (MQTT)
        ↓
AWS IoT Core
        ↓
Kinesis Firehose + S3
        ↓
AWS Glue (ETL)
        ↓
Lambda Inferencia (Modelos)
        ↓
Backend FastAPI
        ↓
Dashboard Web (JavaScript)
```

---

## 🚀 Cómo Usar

### Para explorar la documentación:
```
1. Revisar: Evidencia de documentación/*.docx
2. Especialmente: "Especificación Técnica de Arquitectura.docx"
```

### Para ejecutar el backend:
```
cd Backend/
pip install -r requirements.txt
python -m app.main
```

### Para cargar datos en BD:
```
cd "Base de Datos"
python cargar_datos.py
```

### Para entrenar modelos:
```
Abrir los Jupyter Notebooks:
- Modelo 1 - Diagnóstico/*.ipynb
- Modelo 2 - Vigilancia/*.ipynb
- Modelo 3 - Predicción/*.ipynb
```

### Para desplegar en AWS:
```
cd infraestructura_aws/
python probar_arquitectura_completa.py
python simular_telemetria_continua.py
```

---

## 📌 Notas Importantes

- **Seguridad:** Los certificados AWS y credenciales se encuentran en `edge_gateway/certs/` - NO subir a repositorio público
- **Variables de entorno:** Usar archivos `.env` basados en plantillas `.env.example`
- **Modelos:** Los modelos entrenados están serializados en `lambda_inferencia/artifacts/`
- **Base de datos:** Usa Supabase (PostgreSQL) - requiere conexión a internet
- **Simuladores:** Los scripts de simulación pueden ejecutarse sin acceso real a equipos

---

## 📞 Contacto & Soporte

Para preguntas sobre estructura o contenido, revisar documentos en `Evidencia de documentación/` o contactar al equipo de desarrollo.

**Equipo:**
- Franco Carvajal
- Martín López
- Nicolás Tapia
