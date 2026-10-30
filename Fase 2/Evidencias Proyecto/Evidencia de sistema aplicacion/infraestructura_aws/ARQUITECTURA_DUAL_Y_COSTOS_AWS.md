# Arquitectura Dual (AWS Academy Learner Lab vs. AWS Comercial) y Estimación en AWS Pricing Calculator

> **Proyecto:** Sistema Híbrido de Telemetría y Mantenimiento Predictivo Industrial — *Química Latinoamericana S.A. (Molino Coloidal MC-01)*  
> **Región de Referencia:** `us-east-1` (US East - N. Virginia)

---

## 1. Diseño de Arquitectura Dual (`lab` vs. `prod`)

El sistema fue diseñado para ser **100% agnóstico al tipo de cuenta AWS**, permitiendo desplegar los mismos 3 caminos de datos (**Cold Path**, **ML Path** y **Hot Path**) y el mismo contrato canónico de **31 variables** (`31 -> 11 -> 80`) tanto en un entorno académico restringido (**AWS Academy Learner Lab**) como en una cuenta corporativa estándar (**AWS Comercial / Producción**).

### 1.1. Matriz de Diferencias Técnicas entre Modos

| Componente / Capa | Modo 1: `lab` (AWS Academy Learner Lab) | Modo 2: `prod` (AWS Comercial / Producción) |
| :--- | :--- | :--- |
| **Gobernanza IAM** | Bloqueo por SCP de `iam:CreateRole` y `iam:CreatePolicy`. | Creación de roles dedicados bajo principio de **Mínimo Privilegio (Least-Privilege)**. |
| **Rol de AWS Lambda (`qla-molino-inferencia`)** | `arn:aws:iam::<ACC_ID>:role/LabRole` | `arn:aws:iam::<ACC_ID>:role/QLA_Lambda_Inference_Role` (`dynamodb`, `s3`, `iot:Publish`, `logs`). |
| **Rol de Amazon Data Firehose** | `arn:aws:iam::<ACC_ID>:role/LabRole` | `arn:aws:iam::<ACC_ID>:role/QLA_Firehose_Delivery_Role` (`s3`, `glue:GetTableVersions`, `logs`). |
| **Rol de AWS IoT Topic Rule** | `arn:aws:iam::<ACC_ID>:role/LabRole` | `arn:aws:iam::<ACC_ID>:role/QLA_IoT_Rule_Role` (`firehose:PutRecord`). |
| **Firma WebSocket MQTT (`iot_ws.py`)** | Pre-signed URL SigV4 con credenciales temporales STS (`X-Amz-Security-Token` anexado post-firma). | Pre-signed URL SigV4 compatible tanto con Roles IAM STS (`con token`) como con IAM Users (`sin token`). |
| **Resolución de `IOT_ENDPOINT` y `<ACC_ID>`** | Dinámica en tiempo de ejecución vía `sts:GetCallerIdentity` e `iot:DescribeEndpoint(iot:Data-ATS)`. | Dinámica en tiempo de ejecución vía `sts:GetCallerIdentity` e `iot:DescribeEndpoint(iot:Data-ATS)`. |
| **Bucket S3 Data Lake** | `backup-planta-asfalto-molino-ml` (o con sufijo `-<ACC_ID>` automático si ya existe globalmente). | Configurable vía `-BucketName` o variable `$env:S3_BUCKET`. |

---

## 2. Comandos de Despliegue por Modo

Desde la carpeta `infraestructura_aws/`:

### Opción A: Despliegue en AWS Academy Learner Lab (Por defecto)
No ejecuta ningún comando `iam:CreateRole` ni `iam:PutRolePolicy` y asigna `LabRole` automáticamente:
```powershell
.\desplegar_infraestructura_aws.ps1 -Mode lab
```

### Opción B: Despliegue en Cuenta AWS Normal / Comercial (`prod`)
Ejecuta automáticamente `setup_iam_prod.ps1`, crea los 3 roles IAM de mínimo privilegio (`QLA_Lambda_Inference_Role`, `QLA_Firehose_Delivery_Role`, `QLA_IoT_Rule_Role`) y despliega las 3 rutas con dichos roles:
```powershell
.\desplegar_infraestructura_aws.ps1 -Mode prod
```
*(También puedes definir la variable de entorno `$env:DEPLOY_MODE = "prod"` antes de ejecutar el script).*

---

## 3. Guía Paso a Paso para **AWS Pricing Calculator** (`https://calculator.aws/`)

Para evaluar cuánto cuesta operar esta arquitectura en una cuenta AWS Comercial para **1 Molino Coloidal operando 24/7 (730 horas/mes = 43.800 minutos/mes)** en la región **`us-east-1` (N. Virginia)**, se modelan **dos escenarios operativos**:

1. **Escenario A (Tiempo Real Puro — Alta Frecuencia cada 2 segundos):**
   - El Edge Gateway publica 1 paquete JSON (`~1.2 KB`, 31 variables) cada **2 segundos** ($30\text{ msg/min} = 1.296.000\text{ msg/mes}$).
   - Cada paquete dispara simultáneamente Firehose (Cold Path) y la Lambda Docker de Inferencia ML (ML Path).
2. **Escenario B (Producción Optimizada FinOps/MLOps — Ingesta 5s / Inferencia 10s + Caché Warm Start):**
   - El Edge Gateway publica telemetría cada **5 segundos** ($518.400\text{ msg/mes}$) para visualización en vivo e histórico Parquet.
   - La inferencia predictiva se ejecuta cada **10 segundos** ($259.200\text{ invocaciones/mes}$) y la ventana móvil de 168 horas (`ultimas_168_horas.parquet`) se mantiene en la memoria RAM del contenedor Lambda (Warm Start) y se persiste en S3 **1 vez por minuto** ($43.200\text{ PUT/mes}$).

---

### 3.1. Valores Exactos para Ingresar en `calculator.aws`

#### Bloque 1: **AWS IoT Core**
En el buscador de AWS Pricing Calculator, selecciona **AWS IoT Core** (`US East (N. Virginia)`):
- **Connectivity (Conectividad):**
  - *Number of devices:* `1`
  - *Connection duration:* `43800` minutes/month (24/7)
- **Messaging (Mensajería MQTT):**
  - *Escenario A (2s):* `2,592,000` messages/month (`1,296,000` telemetría entrante + `1,296,000` predicciones salientes, tamaño promedio `1.5 KB` < bloque de `5 KB`).
  - *Escenario B (5s/10s):* `777,600` messages/month (`518,400` telemetría + `259,200` predicciones).
- **Rules Engine (Motor de Reglas):**
  - *Escenario A (2s):* `2,592,000` rules triggered (`2` reglas × `1.296M` mensajes) y `2,592,000` actions executed.
  - *Escenario B (5s/10s):* `777,600` rules triggered y `777,600` actions executed.
- **Subtotal AWS IoT Core:** **$3.45 USD/mes** (Escenario A) | **$1.09 USD/mes** (Escenario B).

---

#### Bloque 2: **AWS Lambda** (Motor de Inferencia ML en Contenedor Docker)
Selecciona **AWS Lambda**:
- **Architecture:** `x86`
- **Allocated Memory:** `2048` MB (`2 GB`, necesario para LightGBM + Autoencoder Keras + Pandas)
- **Ephemeral Storage:** `512` MB (incluido sin costo adicional)
- **Number of requests & Duration:**
  - *Escenario A (2s):* `1,296,000` requests per month | Duration: `150` ms (con caché Warm Start de ventana S3) o `400` ms (sin caché S3).
  - *Escenario B (10s):* `259,200` requests per month | Duration: `150` ms (`77,760 GB-s`, cubierto 100% por el Free Tier permanente de `400,000 GB-s/mes`).
- **Subtotal AWS Lambda:**
  - Sin Free Tier: **$17.54 USD/mes** (Esc. A @ 400ms) | **$6.74 USD/mes** (Esc. A @ 150ms) | **$1.35 USD/mes** (Esc. B @ 150ms).
  - Con Free Tier permanente de cuenta AWS normal: **$10.87 USD/mes** (Esc. A @ 400ms) | **$0.07 USD/mes** (Esc. A @ 150ms) | **$0.00 USD/mes** (Esc. B).

---

#### Bloque 3: **Amazon Elastic Container Registry (ECR)**
Selecciona **Amazon ECR**:
- **Amount of data stored in private repositories:** `2` GB per month (Imagen base Lambda Python 3.12 + dependencias científicas y artefactos `.pkl`/`.keras`).
- **Subtotal Amazon ECR:** **$0.20 USD/mes** (`$0.10/GB-mes`).

---

#### Bloque 4: **Amazon DynamoDB** (Almacenamiento de Estado Reciente e Inferencias)
Selecciona **Amazon DynamoDB** -> **On-Demand Capacity Mode**:
- **Table class:** `DynamoDB Standard`
- **Data storage size:** `3` GB (Escenario A) | `1` GB (Escenario B)
- **On-Demand Write Requests:**
  - Cada registro (`lectura` de 31 variables + `diagnostico` + `vigilancia` + `predictivo`) pesa `~2.8 KB` $\rightarrow$ consume `3 Write Request Units (WRU)` por `PutItem` (`1 WRU` por cada `1 KB`).
  - *Escenario A (2s):* `1,296,000` escrituras $\times 3 = 3,888,000$ write request units/mes.
  - *Escenario B (10s):* `259,200` escrituras $\times 3 = 777,600$ write request units/mes.
- **On-Demand Read Requests:** `100,000` read request units/mes (consultas desde dashboard).
- **Subtotal Amazon DynamoDB:** **$5.62 USD/mes** (Escenario A) | **$1.24 USD/mes** (Escenario B).

---

#### Bloque 5: **Amazon Data Firehose** (Ingesta Cold Path + Conversión Parquet)
Selecciona **Amazon Data Firehose**:
- **Ingestion (Direct PUT and other sources):**
  - *Escenario A (2s):* `1,296,000` records/month, Average record size: `2` KB ($\approx 2.5\text{ GB/mes}$, redondeado al mínimo de facturación por buffer).
  - *Escenario B (5s):* `518,400` records/month, Average record size: `2` KB ($\approx 1.0\text{ GB/mes}$).
- **Data Format Conversion (JSON to Parquet):** Enabled (`$0.018/GB`).
- **Subtotal Amazon Data Firehose:** **$0.12 USD/mes** (Escenario A) | **$0.05 USD/mes** (Escenario B).

---

#### Bloque 6: **Amazon Simple Storage Service (S3)** (Data Lake Parquet + Ventana 168h)
Selecciona **Amazon S3** -> **S3 Standard**:
- **S3 Standard Storage:** `5` GB per month (archivos Parquet comprimidos con Snappy + `ultimas_168_horas.parquet` + `estado_equipos.json`).
- **PUT, COPY, POST, LIST requests:**
  - *Sin caché de minuto en Lambda (cada 2s):* `1,300,000` PUTs/mes $\rightarrow$ **$6.50 USD/mes**.
  - *Con la optimización implementada en `lambda_function.py` (1 PUT/minuto + entregas Firehose):* `45,000` PUTs/mes $\rightarrow$ **$0.23 USD/mes**.
- **GET, SELECT, and all other requests:** `90,000` GETs/mes $\rightarrow$ **$0.04 USD/mes**.
- **Subtotal Amazon S3:** **$7.66 USD/mes** (Esc. A sin caché) | **$0.38 USD/mes** (Con caché de 1 min implementado).

---

#### Bloque 7: **AWS Glue + Amazon Athena** (Consultas Analíticas sobre Data Lake)
Selecciona **Amazon Athena**:
- **AWS Glue Data Catalog:** Gratis (1 tabla `telemetria_molino` con **Partition Projection** activado en `glue_table.json`, por lo que consume `0` ejecuciones de Glue Crawler y `< 1,000,000` objetos).
- **Athena SQL Queries:** `10` GB de datos escaneados al mes (gracias al formato columnar Parquet Snappy y particionamiento `year/month/day`, `10 GB` equivalen a cientos de consultas históricas al mes).
- **Subtotal Glue + Athena:** **$0.05 USD/mes** (`$5.00 por TB` escaneado).

---

#### Bloque 8: **Amazon CloudWatch** (Logs y Observabilidad)
Selecciona **Amazon CloudWatch**:
- **CloudWatch Logs Ingested:**
  - *Escenario A (2s):* `3` GB/mes (**$1.50 USD/mes** sin Free Tier, **$0.00** con los `5 GB` gratis del Free Tier permanente).
  - *Escenario B (10s):* `0.5` GB/mes (**$0.00 USD/mes**).

---

## 4. Resumen Ejecutivo de Costos Mensuales (Por Activo / Molino Coloidal)

| Escenario de Operación (24/7 - 730 h/mes) | Sin Free Tier Permanente | Con Free Tier Permanente AWS | Costo Anual Estimado (Con Free Tier) |
| :--- | :---: | :---: | :---: |
| **Escenario A1:** Cada 2s sin caché S3 en Lambda | **$36.14 USD / mes** | **$27.97 USD / mes** | ~$335.64 USD / año |
| **Escenario A2:** Cada 2s **con caché S3 por minuto** *(Implementado)* | **$18.06 USD / mes** | **$9.89 USD / mes** | ~$118.68 USD / año |
| **Escenario B (Recomendado Producción):** Ingesta 5s / Inferencia 10s + Caché S3 | **$4.36 USD / mes** | **$3.01 USD / mes** | **~$36.12 USD / año** |
