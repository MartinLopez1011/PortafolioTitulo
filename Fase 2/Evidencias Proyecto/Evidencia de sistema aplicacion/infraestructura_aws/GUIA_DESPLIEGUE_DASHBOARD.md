# Despliegue del dashboard en AWS (Learner Lab)

Completa la arquitectura que ya está en el lab (IoT Core → Lambda de inferencia → DynamoDB / S3) con:

```
Simulador ──MQTT──> IoT Core ──> Lambda qla-molino-inferencia ──> DynamoDB QLA_Molino_Telemetria
                                                                        │ (Stream NEW_IMAGE)
                                                                        ▼
Navegador ──HTTPS──> API Gateway ──HTTP──> EC2 qla-servidor  <── Lambda qla-persistencia
                                        (FastAPI + web)              (POST /api/ingesta/registro)
                                              │
                                              ▼
                                        RDS PostgreSQL qla-mantpred
```

| Recurso | Para qué |
|---|---|
| EC2 `qla-servidor` (t3.small, Amazon Linux 2023) | Backend FastAPI y la web, en el puerto 80. Al arrancar descarga el último código de S3. |
| IP elástica | La dirección del servidor no cambia entre sesiones del lab. |
| API Gateway `qla-dashboard` | Dirección HTTPS pública del dashboard. |
| Lambda `qla-persistencia` | Lee el Stream de DynamoDB y envía cada resultado al backend, que lo guarda en RDS y lo muestra en vivo. Si el servidor está apagado, el Stream reintenta hasta 6 h: no se pierden resultados. |
| Grupo de seguridad `qla-web-sg` | Solo abre el puerto 80. RDS acepta el puerto 5432 únicamente desde este grupo (y desde tu IP). |

## Antes de empezar (una sola vez)

1. Inicia el lab (**Start Lab**, punto verde) y copia las credenciales de **AWS Details** al Bloc de notas en `C:\Users\nicol\.aws\credentials`. No las pegues en PowerShell ni en el chat.
2. Abre PowerShell en `infraestructura_aws` y activa el entorno:
   ```powershell
   cd "C:\Users\nicol\Documents\PortafolioTitulo\Fase 2\Evidencias Proyecto\Evidencia de sistema aplicacion\infraestructura_aws"
   .\.venv\Scripts\Activate.ps1
   aws sts get-caller-identity
   ```
3. **Crea tu administrador y desactiva los usuarios de prueba.** La clave de los usuarios `@demo.qla.cl` está publicada en el repositorio, así que hay que desactivarlos antes de que el servidor sea público:
   ```powershell
   python "..\Base de Datos\crear_admin.py" --env "$HOME\qla_rds.env"
   ```
   Pide nombre, correo y clave (la clave no se ve al escribirla). Se puede volver a ejecutar para cambiar la clave.

## Desplegar

```powershell
powershell -ExecutionPolicy Bypass -File .\desplegar_dashboard_aws.ps1
```

Tarda unos 6 a 8 minutos (la primera vez el servidor instala Python y las librerías). Al final muestra:

```
 Dashboard (HTTPS): https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
 Dashboard (HTTP, con tiempo real): http://3.x.x.x
```

* Por HTTPS el dashboard se actualiza de forma periódica (API Gateway HTTP no transmite WebSocket).
* Por HTTP, con la IP, también funciona el canal en vivo.

El script guarda `JWT_SECRET` y `CLAVE_INGESTA` en `C:\Users\nicol\qla_servidor.env`, fuera del repositorio. No lo subas a Git ni lo compartas.

## Probar el flujo completo

1. Entra al dashboard con el administrador que creaste.
2. En otra ventana de PowerShell (con el entorno activado) envía telemetría:
   ```powershell
   python simular_telemetria_continua.py --intervalo 5 --cantidad 60
   ```
3. Comprueba que los resultados llegan a RDS:
   ```powershell
   aws logs tail /aws/lambda/qla-persistencia --since 10m
   ```
   Debe mostrar líneas `[OK] recibidos=… guardados=…`. En `https://…/docs` puedes probar `GET /api/proceso`.
4. Para ver una falla: `python simular_telemetria_continua.py --intervalo 5 --cantidad 20 --modo clogged_filter`. La alarma se abre cuando la condición se cumple en 3 de los últimos 5 minutos con datos.

> **Antes de presentar:** envía unas lecturas 10 minutos antes. La primera invocación de la Lambda de inferencia tarda entre 8 y 43 s (arranque en frío); después, unos 150 ms.

## Uso diario

| Necesito… | Comando |
|---|---|
| Ver direcciones y estado | `.\desplegar_dashboard_aws.ps1 -Accion estado` |
| Encender el servidor en una nueva sesión del lab | `.\desplegar_dashboard_aws.ps1 -Accion iniciar` |
| Subir cambios del backend o de la web | `.\desplegar_dashboard_aws.ps1 -Accion actualizar` |
| Apagar el servidor al terminar | `.\desplegar_dashboard_aws.ps1 -Accion detener` |

Al terminar la sesión, el lab apaga la EC2 automáticamente, pero **RDS sigue encendida**. Si no la vas a usar en varios días:
`aws rds stop-db-instance --db-instance-identifier qla-mantpred` (y `-Accion iniciar` la vuelve a encender).

## Costo aproximado (crédito de USD 50)

| Recurso | Precio | Cuándo cobra |
|---|---|---|
| EC2 t3.small | ~USD 0,021/h | solo encendida |
| IP elástica | ~USD 0,005/h | siempre (~USD 0,12/día) |
| RDS db.t3.micro + 20 GB | ~USD 0,017/h + ~USD 0,08/día | siempre, salvo que se detenga |
| API Gateway, Lambda, DynamoDB | centavos | por uso |

Con sesiones de 4 h al día hasta el 16 de noviembre el gasto queda bajo USD 15. Revisa el saldo en la página del lab: se actualiza cada 8 a 12 h, y si se superan los USD 50 el lab borra todo.

## Si algo falla

* **El script no termina de responder:** revisa el registro de arranque del servidor con `aws ec2 get-console-output --instance-id <id> --latest --output text`. Busca errores de `dnf` o `pip`.
* **"La API responde pero la base no":** RDS está detenida o el grupo de seguridad de RDS no tiene la regla desde `qla-web-sg`. Vuelve a ejecutar el script sin `-Accion`: es seguro repetirlo y completa lo que falte.
* **La Lambda muestra `HTTP 401`:** la `CLAVE_INGESTA` de la Lambda no coincide con la del servidor. Vuelve a ejecutar el script sin `-Accion`.
* **Errores al pegar en el chat:** quita antes cualquier clave, token o cadena de conexión.
