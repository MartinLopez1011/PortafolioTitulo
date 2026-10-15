# Guía de Despliegue de Infraestructura AWS y Arquitectura de 3 Rutas (AWS Academy)

Este documento contiene la arquitectura completa, secuencia de comandos CLI y configuraciones validadas en **AWS Academy Learner Lab** (región `us-east-1`) para el sistema de predicción y diagnóstico del Molino Coloidal QLA.

---

## 🏗️ Arquitectura del Sistema (3 Rutas)

```
                              [ Edge Gateway / Planta ]
                                          |
                              (MQTT / IoT Core Topic)
                        'planta/asfalto/molino/telemetria'
                                  /       |       \
                                 /        |        \
    -----------------------------         |         -----------------------------
   |                                      |                                      |
   v                                      v                                      v
[ RUTA 1: Cold Path ]            [ RUTA 2: ML Path ]                    [ RUTA 3: Hot Path ]
Amazon Data Firehose             AWS IoT Rule                           AWS IoT Core Broker
  - Buffer 60s / 64MB              - Regla_Inferencia_Molino             (MQTT sobre WebSockets)
  - OpenX JSON SerDe                      |                                       |
  - Parquet Converter (Snappy)            v                                       |
  - Prefix YYYY/MM/DD            AWS Lambda (Container 3008 MB)                   |
          |                        - Inferencia Etapa 1, 2 y 3                    |
          v                        - Bitácora y Ventana S3                        |
Amazon S3 Data Lake                       |                                       |
(Parquet temporal particionado)    +------+------+                                |
          |                        |             |                                |
          v                        v             v                                |
AWS Glue Data Catalog         DynamoDB       IoT Topic                            |
(Partition Projection)      (Historial)   (Predicciones)                          |
          |                                      |                                |
          v                                      +--------------------------------+
Amazon Athena                                                                     |
(Serverless SQL)                                                                  v
                                                                        [ Frontend Dashboard ]
                                                                        - Paho MQTT WebSocket
                                                                        - Pre-firmado SigV4
                                                                        - Badge "En vivo (MQTT)"
                                                                        - Fallback Polling 60s
```

---

## 📌 Consideraciones Clave en AWS Academy
1. **Restricción de IAM**: En AWS Academy (`voclabs`) no se permite crear roles (`iam:CreateRole`) ni adjuntar políticas a roles.
2. **Rol de Ejecución**: Se utiliza el rol pre-creado del laboratorio:
   ```text
   arn:aws:iam::441381011844:role/LabRole
   ```
3. **Formato de Imagen Docker para Lambda**: AWS Lambda requiere imágenes en formato **Docker V2 Schema 2** sin atestaciones OCI (`--provenance=false --sbom=false --output type=registry,oci-mediatypes=false`).
4. **AWS IoT Endpoint**: ATS Endpoint asignado a la cuenta:
   ```text
   a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com
   ```

---

## 🧊 RUTA 1: Cold Path (Históricos y Analítica a Largo Plazo)

### 1.1 Repositorio S3 Data Lake
El bucket central de almacenamiento es:
```bash
aws s3 mb s3://backup-planta-asfalto-molino-ml --region us-east-1
```

### 1.2 Base de Datos y Tabla en AWS Glue Data Catalog
Se crea la base de datos `qla_planta_asfalto`:
```bash
aws glue create-database --database-input file://glue_database.json --region us-east-1
```

Se crea la tabla `telemetria_molino` en formato Parquet, con partición temporal (`year`, `month`, `day`) y **Partition Projection** habilitado:
```bash
aws glue create-table --database-name qla_planta_asfalto --table-input file://glue_table.json --region us-east-1
```

> **Nota sobre Partition Projection**: Los parámetros `projection.enabled: true` permiten que Amazon Athena consulte directamente cualquier partición temporal generada por Firehose sin necesidad de ejecutar rastreadores Glue (Crawlers) ni `MSCK REPAIR TABLE`.

### 1.3 Amazon Data Firehose (Conversión Parquet en vuelo)
El delivery stream `stream-backup-planta-asfalto` convierte los eventos JSON continuos a Apache Parquet (Snappy) en ventanas de 60 segundos o 64 MiB y los escribe bajo el prefijo `historico/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/`:
```bash
aws firehose update-destination \
  --delivery-stream-name stream-backup-planta-asfalto \
  --current-delivery-stream-version-id 1 \
  --destination-id destinationId-000000000001 \
  --extended-s3-destination-update file://firehose_update.json \
  --region us-east-1
```

### 1.4 Regla IoT Core hacia Firehose
La regla `Regla_S3_Historico_Molino` enruta el flujo del topic `planta/asfalto/molino/telemetria` hacia Firehose con separador `\n`:
```bash
aws iot replace-topic-rule \
  --rule-name Regla_S3_Historico_Molino \
  --topic-rule-payload file://iot_rule_firehose.json \
  --region us-east-1
```

### 1.5 Capa de Consulta: Amazon Athena
Configuración del WorkGroup `primary` para guardar resultados de consultas:
```bash
aws athena update-work-group \
  --work-group primary \
  --configuration-updates "ResultConfigurationUpdates={OutputLocation=s3://backup-planta-asfalto-molino-ml/athena_results/}" \
  --region us-east-1
```

Ejemplo de consulta serverless SQL:
```sql
SELECT equipo_id, estado_operacion, tipo_asfalto, tem_son_betum_in, amp_vfd_motor_molino, rpm_motor_molino
FROM qla_planta_asfalto.telemetria_molino
WHERE year = '2026' AND month = '10'
ORDER BY timestamp DESC
LIMIT 50;
```

---

##  RUTA 2: ML Path (Inferencia Predictiva en Tiempo Real)

### 2.1 Tabla DynamoDB
Tabla para el registro histórico y operacional de diagnósticos y salud de instrumentos:
```bash
aws dynamodb create-table \
  --table-name QLA_Molino_Telemetria \
  --attribute-definitions \
      AttributeName=equipo_id,AttributeType=S \
      AttributeName=timestamp,AttributeType=N \
  --key-schema \
      AttributeName=equipo_id,KeyType=HASH \
      AttributeName=timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### 2.2 Compilar y Publicar Contenedor en ECR
```powershell
.\build_and_push_ecr.ps1
```

### 2.3 Función AWS Lambda
Configurada con **3008 MB** de RAM (óptimo para carga de TensorFlow/Keras, Autoencoder y Random Forest en warm-start):
```bash
aws lambda create-function \
  --function-name qla-molino-inferencia \
  --package-type Image \
  --code ImageUri=441381011844.dkr.ecr.us-east-1.amazonaws.com/qla-molino-inferencia:latest \
  --role arn:aws:iam::441381011844:role/LabRole \
  --timeout 60 \
  --memory-size 3008 \
  --region us-east-1
```

### 2.4 Regla IoT Core para Inferencia Automática
La regla `Regla_Inferencia_Molino` invoca la función Lambda con cada mensaje en el topic de telemetría:
- **SQL**: `SELECT * FROM 'planta/asfalto/molino/telemetria'`
- **Acción**: `lambda: qla-molino-inferencia`

---

## 🌐 RUTA 3: Hot Path (Transmisión en Tiempo Real para el Dashboard Web)

### 3.1 Política AWS IoT Core
La política `PlantaAsfalto_Molino_Policy` otorga permisos de conexión, publicación y suscripción MQTT:
- `iot:Connect` en `arn:aws:iot:*:*:client/*`
- `iot:Publish`, `iot:Receive` en `arn:aws:iot:*:*:topic/planta/asfalto/*`
- `iot:Subscribe` en `arn:aws:iot:*:*:topicfilter/planta/asfalto/*`

### 3.2 Endpoint Pre-firmado SigV4 en Backend FastAPI
El backend expone `GET /api/iot/ws-url` en `app/rutas/planta.py` y `app/iot_ws.py`. Genera dinámicamente URLs pre-firmadas WebSocket para el servicio `iotdevicegateway`:
```text
wss://a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com/mqtt?X-Amz-Algorithm=AWS4-HMAC-SHA256&...
```

### 3.3 Cliente MQTT en Frontend Dashboard
1. Biblioteca local en `web/js/vendor/paho-mqtt.min.js`.
2. Conexión WebSocket directa desde el navegador mediante Paho MQTT.
3. Suscripción automática a:
   - `planta/asfalto/molino/telemetria`
   - `planta/asfalto/molino/predicciones`
4. Indicador visual en cabecera con badge interactivo:
   - `<span class="chip en-vivo"><span class="punto"></span>En vivo (MQTT)</span>` (conexión activa en tiempo real).
   - `<span class="chip offline"><span class="punto"></span>Polling (60s)</span>` (fallback seguro si se interrumpe la red).

---

## 🧪 Pruebas de Validación End-to-End

### Prueba de Publicación de Telemetría
```bash
aws iot-data publish \
  --topic "planta/asfalto/molino/telemetria" \
  --payload fileb://../lambda_inferencia/app/test_payload_flat.json \
  --cli-binary-format raw-in-base64-out \
  --region us-east-1
```

### Resultados de la Prueba:
1. **Ruta 1 (Cold Path)**: Genera archivo `.parquet` en `s3://backup-planta-asfalto-molino-ml/historico/year=2026/month=10/day=15/` en 60 segundos. Consulta exitosa con Athena.
2. **Ruta 2 (ML Path)**: Lambda ejecuta la inferencia en ~80 ms, persiste en `QLA_Molino_Telemetria` y publica el diagnóstico en `planta/asfalto/molino/predicciones`.
3. **Ruta 3 (Hot Path)**: El dashboard web recibe el evento instantáneamente por WebSocket y actualiza el panel sin recargar la página.
