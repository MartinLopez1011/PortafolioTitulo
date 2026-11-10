# ==============================================================================
# Despliegue del dashboard en AWS (Learner Lab): backend + web en EC2, HTTPS con
# API Gateway y Lambda qla-persistencia (DynamoDB Stream -> backend -> RDS).
#
# Requisitos: credenciales del lab en ~/.aws/credentials, la infraestructura de
# desplegar_infraestructura_aws.ps1 ya creada (bucket, DynamoDB con Stream) y la
# base RDS con el esquema v2 + migracion_v3. Ejecutar antes crear_admin.py.
#
# Uso (desde infraestructura_aws):
#   .\desplegar_dashboard_aws.ps1                       # crea o completa todo
#   .\desplegar_dashboard_aws.ps1 -Accion actualizar    # sube el código nuevo y reinicia
#   .\desplegar_dashboard_aws.ps1 -Accion estado        # muestra direcciones y estado
#   .\desplegar_dashboard_aws.ps1 -Accion iniciar       # enciende el servidor (nueva sesión)
#   .\desplegar_dashboard_aws.ps1 -Accion detener       # apaga el servidor (ahorra crédito)
#
# Los secretos (clave de la base, JWT, clave de ingesta) NO se muestran en pantalla.
#
# NOTA CI/CD: desde que existe .github/workflows/cd.yml, las actualizaciones del backend se
# despliegan automáticamente como contenedor Docker (ECR qla-backend) al hacer merge a main.
# El primer deploy desactiva el servicio systemd "qla". No usar "-Accion actualizar" después
# de esa migración (ver docs/CICD.md). Este script sigue siendo válido para crear la infraestructura.
# ==============================================================================
param(
    [ValidateSet("desplegar", "actualizar", "estado", "iniciar", "detener")]
    [string]$Accion = "desplegar",
    [string]$BucketName = "qla-molino-nicolas-2026",
    [string]$ArchivoRds = "$HOME\qla_rds.env",
    [string]$InstanciaRds = "qla-mantpred",
    [string]$TipoInstancia = "t3.small",
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Continue"   # los errores se revisan con $LASTEXITCODE
$env:AWS_DEFAULT_REGION = $Region
$env:AWS_PAGER = ""
$NOMBRE = "qla-servidor"
$SG_WEB = "qla-web-sg"
$API_NOMBRE = "qla-dashboard"
$LAMBDA = "qla-persistencia"
$TABLA = "QLA_Molino_Telemetria"
$AQUI = $PSScriptRoot
$BACKEND = (Resolve-Path (Join-Path $AQUI "..\Backend")).Path
$SECRETOS = "$HOME\qla_servidor.env"
$TMP = Join-Path $env:TEMP "qla_despliegue"
New-Item -ItemType Directory -Force -Path $TMP | Out-Null

function Paso($t) { Write-Host "`n>> $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "   [OK] $t" -ForegroundColor Green }
function Falla($t) { Write-Host "   [ERROR] $t" -ForegroundColor Red; exit 1 }
function Ejecutar-Aws { $s = & aws @args; if ($LASTEXITCODE -ne 0) { Falla "aws $($args[0]) $($args[1]) falló" }; return $s }
function Vacio($v) { return (-not $v) -or ($v -eq "None") }
function Escribir-LF($ruta, $texto) {
    [IO.File]::WriteAllText($ruta, $texto.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
}
function Leer-Var($archivo, $nombre) {
    foreach ($l in Get-Content $archivo) {
        if ($l -match "^\s*$nombre\s*=\s*(.+)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}
function Aleatorio($bytes) {
    $b = New-Object byte[] $bytes
    (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($b)
    return ([BitConverter]::ToString($b) -replace "-", "").ToLower()
}

function Instancia {
    $id = aws ec2 describe-instances --filters "Name=tag:Name,Values=$NOMBRE" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query "Reservations[0].Instances[0].InstanceId" --output text
    if (Vacio $id) { return $null } else { return $id }
}
function Url-Api {
    $id = aws apigatewayv2 get-apis --query "Items[?Name=='$API_NOMBRE'].ApiId | [0]" --output text
    if (Vacio $id) { return $null }
    return "https://$id.execute-api.$Region.amazonaws.com"
}
function Ip-Elastica {
    $ip = aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NOMBRE" --query "Addresses[0].PublicIp" --output text
    if (Vacio $ip) { return $null } else { return $ip }
}
function Esperar-Salud($url) {
    Write-Host "   Esperando que el servidor responda en $url/api/salud (la primera vez tarda 3 a 5 min)..."
    for ($i = 0; $i -lt 48; $i++) {
        try {
            $r = Invoke-RestMethod -Uri "$url/api/salud" -TimeoutSec 10
            if ($r.base_de_datos -eq "ok") { Ok "Servidor y base de datos responden"; return $true }
            Write-Host "   La API responde pero la base no: $($r | ConvertTo-Json -Compress)" -ForegroundColor Yellow
        } catch { }
        Start-Sleep -Seconds 15
    }
    Write-Host "   [AVISO] No respondió a tiempo. Revisa el registro con:" -ForegroundColor Yellow
    Write-Host "   aws ec2 get-console-output --instance-id $(Instancia) --latest --output text" -ForegroundColor Yellow
    return $false
}
function Mostrar-Direcciones {
    $api = Url-Api; $ip = Ip-Elastica
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    if ($api) { Write-Host " Dashboard (HTTPS): $api" -ForegroundColor Green }
    if ($ip) { Write-Host " Dashboard (HTTP, con tiempo real): http://$ip" -ForegroundColor Green }
    if ($api) { Write-Host " Documentación API: $api/docs" }
    Write-Host "==================================================================" -ForegroundColor Cyan
}
function Subir-Codigo {
    Paso "Empaquetando el backend y la web (sin .env) y subiéndolo a S3"
    $tgz = Join-Path $TMP "backend.tgz"
    if (Test-Path $tgz) { Remove-Item $tgz }
    tar -czf $tgz --exclude=.env --exclude=__pycache__ --exclude=*.pyc --exclude=.venv -C $BACKEND app web requirements.txt
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo empaquetar $BACKEND" }
    Ejecutar-Aws s3 cp $tgz "s3://$BucketName/despliegue/backend.tgz" --only-show-errors | Out-Null
    Ok "Código subido a s3://$BucketName/despliegue/backend.tgz"
    # El simulador del dashboard reproduce el año 2026: el servidor descarga el dataset desde S3
    aws s3 ls "s3://$BucketName/despliegue/Dataset_Molino_QLA_Realista.zip" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dataset = Join-Path $AQUI "..\Dataset Simulado\Dataset_Molino_QLA_Realista.zip"
        if (-not (Test-Path $dataset)) { Falla "No se encontró $dataset" }
        Ejecutar-Aws s3 cp $dataset "s3://$BucketName/despliegue/Dataset_Molino_QLA_Realista.zip" --only-show-errors | Out-Null
        Ok "Dataset del simulador subido a S3 (34 MB, solo la primera vez)"
    }
}

# ------------------------------------------------------------------------------
Paso "Verificando credenciales del lab"
$CUENTA = aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0 -or (Vacio $CUENTA)) { Falla "Credenciales no válidas. Copia las de AWS Details a ~/.aws/credentials" }
Ok "Cuenta $CUENTA"

if ($Accion -eq "estado") {
    $id = Instancia
    if ($id) { Write-Host "   Servidor $id : $(aws ec2 describe-instances --instance-ids $id --query 'Reservations[0].Instances[0].State.Name' --output text)" }
    else { Write-Host "   No hay servidor creado" }
    Write-Host "   RDS $InstanciaRds : $(aws rds describe-db-instances --db-instance-identifier $InstanciaRds --query 'DBInstances[0].DBInstanceStatus' --output text)"
    Write-Host "   Lambda $LAMBDA : $(aws lambda get-function --function-name $LAMBDA --query 'Configuration.State' --output text 2>$null)"
    Mostrar-Direcciones; exit 0
}
if ($Accion -eq "detener") {
    $id = Instancia; if (-not $id) { Falla "No hay servidor" }
    Ejecutar-Aws ec2 stop-instances --instance-ids $id | Out-Null
    Ok "Servidor deteniéndose. Los resultados que lleguen mientras tanto quedan en DynamoDB y se reintentan hasta 6 h."
    Write-Host "   La base RDS sigue encendida (cobra aunque no se use). Para apagarla unos días:" -ForegroundColor Yellow
    Write-Host "   aws rds stop-db-instance --db-instance-identifier $InstanciaRds   (AWS la vuelve a encender a los 7 días)" -ForegroundColor Yellow
    exit 0
}
if ($Accion -eq "iniciar") {
    $id = Instancia; if (-not $id) { Falla "No hay servidor. Ejecuta sin -Accion para crearlo" }
    $rds = aws rds describe-db-instances --db-instance-identifier $InstanciaRds --query "DBInstances[0].DBInstanceStatus" --output text
    if ($rds -eq "stopped") { Ejecutar-Aws rds start-db-instance --db-instance-identifier $InstanciaRds | Out-Null; Ok "Encendiendo RDS (tarda unos minutos)" }
    Ejecutar-Aws ec2 start-instances --instance-ids $id | Out-Null
    Ejecutar-Aws ec2 wait instance-running --instance-ids $id
    Ok "Servidor encendido (descarga el último código de S3 al arrancar)"
    Esperar-Salud (Url-Api) | Out-Null; Mostrar-Direcciones; exit 0
}
if ($Accion -eq "actualizar") {
    $id = Instancia; if (-not $id) { Falla "No hay servidor. Ejecuta sin -Accion para crearlo" }
    Subir-Codigo
    Paso "Reiniciando el servicio para que tome el código nuevo"
    $cmd = aws ssm send-command --instance-ids $id --document-name AWS-RunShellScript --parameters "commands=systemctl restart qla" --query "Command.CommandId" --output text 2>$null
    if ($LASTEXITCODE -ne 0 -or (Vacio $cmd)) {
        Write-Host "   SSM no disponible: reinicio la instancia completa" -ForegroundColor Yellow
        Ejecutar-Aws ec2 reboot-instances --instance-ids $id | Out-Null
        Start-Sleep -Seconds 30
    }
    Esperar-Salud (Url-Api) | Out-Null; Mostrar-Direcciones; exit 0
}

# =========================== DESPLIEGUE COMPLETO ==============================
Paso "Leyendo la conexión a RDS de $ArchivoRds (no se muestra)"
if (-not (Test-Path $ArchivoRds)) { Falla "No existe $ArchivoRds" }
$DATABASE_URL = Leer-Var $ArchivoRds "DATABASE_URL"
if (-not $DATABASE_URL) { Falla "$ArchivoRds no tiene DATABASE_URL" }
Ok "Conexión leída"

if (-not (Test-Path $SECRETOS)) {
    "JWT_SECRET=$(Aleatorio 48)`r`nCLAVE_INGESTA=$(Aleatorio 32)" | Set-Content -Path $SECRETOS -Encoding ASCII
    Ok "Secretos nuevos guardados en $SECRETOS (fuera del repositorio)"
}
$JWT_SECRET = Leer-Var $SECRETOS "JWT_SECRET"
$CLAVE_INGESTA = Leer-Var $SECRETOS "CLAVE_INGESTA"

Paso "Ubicando la red de la base RDS"
$VPC = Ejecutar-Aws rds describe-db-instances --db-instance-identifier $InstanciaRds --query "DBInstances[0].DBSubnetGroup.VpcId" --output text
$SG_RDS = Ejecutar-Aws rds describe-db-instances --db-instance-identifier $InstanciaRds --query "DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId" --output text
$SUBRED = Ejecutar-Aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" "Name=default-for-az,Values=true" --query "Subnets[0].SubnetId" --output text
if (Vacio $SUBRED) { $SUBRED = Ejecutar-Aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --query "Subnets[0].SubnetId" --output text }
Ok "VPC $VPC, subred $SUBRED, grupo de RDS $SG_RDS"

Paso "Grupo de seguridad del servidor ($SG_WEB)"
$SG = aws ec2 describe-security-groups --filters "Name=group-name,Values=$SG_WEB" "Name=vpc-id,Values=$VPC" --query "SecurityGroups[0].GroupId" --output text
if (Vacio $SG) {
    $SG = Ejecutar-Aws ec2 create-security-group --group-name $SG_WEB --description "QLA dashboard HTTP" --vpc-id $VPC --query GroupId --output text
    Ejecutar-Aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 80 --cidr 0.0.0.0/0 | Out-Null
    Ok "Creado $SG (solo puerto 80 abierto; sin SSH)"
} else { Ok "Ya existe $SG" }
aws ec2 authorize-security-group-ingress --group-id $SG_RDS --protocol tcp --port 5432 --source-group $SG 2>$null | Out-Null
Ok "RDS acepta conexiones desde el servidor (puerto 5432)"

Subir-Codigo

$ID = Instancia
if (-not $ID) {
    Paso "Creando el servidor EC2 $TipoInstancia (Amazon Linux 2023)"
    $AMI = Ejecutar-Aws ssm get-parameters --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query "Parameters[0].Value" --output text
    $plantilla = @'
#!/bin/bash
# No usar "set -x": escribiría los secretos en el registro de la instancia
set -euo pipefail
dnf install -y python3.11 python3.11-pip tar
mkdir -p /opt/qla/Backend
cat > /opt/qla/Backend/.env <<'FIN_ENV'
DATABASE_URL=__DATABASE_URL__
JWT_SECRET=__JWT_SECRET__
CLAVE_INGESTA=__CLAVE_INGESTA__
FIN_ENV
chown ec2-user /opt/qla/Backend/.env
chmod 600 /opt/qla/Backend/.env
cat > /opt/qla/actualizar.sh <<'FIN_ACT'
#!/bin/bash
set -euo pipefail
cd /opt/qla
aws s3 cp s3://__BUCKET__/despliegue/backend.tgz backend.tgz --region __REGION__ --only-show-errors
rm -rf Backend/app Backend/web
tar -xzf backend.tgz -C Backend
[ -x venv/bin/python ] || python3.11 -m venv venv
venv/bin/pip install -q --disable-pip-version-check -r Backend/requirements.txt
FIN_ACT
chmod 700 /opt/qla/actualizar.sh
cat > /etc/systemd/system/qla.service <<'FIN_SVC'
[Unit]
Description=Dashboard QLA (FastAPI)
Wants=network-online.target
After=network-online.target

[Service]
User=ec2-user
WorkingDirectory=/opt/qla/Backend
ExecStartPre=+/opt/qla/actualizar.sh
ExecStart=/opt/qla/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
RestartSec=5
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
FIN_SVC
systemctl daemon-reload
systemctl enable --now qla
'@
    $ud = $plantilla.Replace("__DATABASE_URL__", $DATABASE_URL).Replace("__JWT_SECRET__", $JWT_SECRET)
    $ud = $ud.Replace("__CLAVE_INGESTA__", $CLAVE_INGESTA).Replace("__BUCKET__", $BucketName).Replace("__REGION__", $Region)
    $udArchivo = Join-Path $TMP "user-data.sh"
    Escribir-LF $udArchivo $ud
    try {
        $ID = Ejecutar-Aws ec2 run-instances --image-id $AMI --instance-type $TipoInstancia --subnet-id $SUBRED `
            --security-group-ids $SG --associate-public-ip-address `
            --iam-instance-profile Name=LabInstanceProfile `
            --metadata-options "HttpTokens=required,HttpEndpoint=enabled" `
            --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NOMBRE}]" `
            --user-data "file://$udArchivo" --query "Instances[0].InstanceId" --output text
    } finally { Remove-Item $udArchivo -ErrorAction SilentlyContinue }   # el archivo tenía los secretos
    Ok "Instancia $ID creada; esperando que esté en marcha"
    Ejecutar-Aws ec2 wait instance-running --instance-ids $ID
} else {
    Ok "Ya existe el servidor $ID"
    $estado = Ejecutar-Aws ec2 describe-instances --instance-ids $ID --query "Reservations[0].Instances[0].State.Name" --output text
    if ($estado -eq "stopped") { Ejecutar-Aws ec2 start-instances --instance-ids $ID | Out-Null; Ejecutar-Aws ec2 wait instance-running --instance-ids $ID; Ok "Encendido" }
}

Paso "IP elástica (la dirección no cambia entre sesiones del lab)"
$IP = Ip-Elastica
if (-not $IP) {
    $ALLOC = Ejecutar-Aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NOMBRE}]" --query AllocationId --output text
    $IP = Ip-Elastica
} else {
    $ALLOC = Ejecutar-Aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NOMBRE" --query "Addresses[0].AllocationId" --output text
}
Ejecutar-Aws ec2 associate-address --instance-id $ID --allocation-id $ALLOC --allow-reassociation | Out-Null
Ok "IP $IP asociada al servidor"

Paso "API Gateway HTTPS ($API_NOMBRE)"
$API_URL = Url-Api
if (-not $API_URL) {
    $API = Ejecutar-Aws apigatewayv2 create-api --name $API_NOMBRE --protocol-type HTTP --query ApiId --output text
    $INT1 = Ejecutar-Aws apigatewayv2 create-integration --api-id $API --integration-type HTTP_PROXY --integration-method ANY `
        --integration-uri "http://$IP/{proxy}" --payload-format-version 1.0 --query IntegrationId --output text
    $INT2 = Ejecutar-Aws apigatewayv2 create-integration --api-id $API --integration-type HTTP_PROXY --integration-method ANY `
        --integration-uri "http://$IP/" --payload-format-version 1.0 --query IntegrationId --output text
    Ejecutar-Aws apigatewayv2 create-route --api-id $API --route-key "ANY /{proxy+}" --target "integrations/$INT1" | Out-Null
    Ejecutar-Aws apigatewayv2 create-route --api-id $API --route-key "ANY /" --target "integrations/$INT2" | Out-Null
    Ejecutar-Aws apigatewayv2 create-stage --api-id $API --stage-name '$default' --auto-deploy | Out-Null
    $API_URL = Url-Api
    Ok "Creada: $API_URL"
} else { Ok "Ya existe: $API_URL" }

Paso "Lambda $LAMBDA (DynamoDB Stream -> backend -> RDS)"
$zip = Join-Path $TMP "lambda_persistencia.zip"
if (Test-Path $zip) { Remove-Item $zip }
tar -a -cf $zip -C (Join-Path $AQUI "lambda_persistencia") lambda_function.py
if ($LASTEXITCODE -ne 0) { Falla "No se pudo comprimir la Lambda" }
$ROL = "arn:aws:iam::${CUENTA}:role/LabRole"
$VARS = "Variables={URL_BACKEND=$API_URL,CLAVE_INGESTA=$CLAVE_INGESTA,FUENTE=simulado}"
aws lambda get-function --function-name $LAMBDA 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Ejecutar-Aws lambda create-function --function-name $LAMBDA --runtime python3.12 --role $ROL `
        --handler lambda_function.lambda_handler --zip-file "fileb://$zip" --timeout 60 --memory-size 256 `
        --environment $VARS | Out-Null
    Ejecutar-Aws lambda wait function-active --function-name $LAMBDA
    Ok "Creada"
} else {
    Ejecutar-Aws lambda update-function-code --function-name $LAMBDA --zip-file "fileb://$zip" | Out-Null
    Ejecutar-Aws lambda wait function-updated --function-name $LAMBDA
    Ejecutar-Aws lambda update-function-configuration --function-name $LAMBDA --environment $VARS | Out-Null
    Ejecutar-Aws lambda wait function-updated --function-name $LAMBDA
    Ok "Actualizada"
}
$STREAM = Ejecutar-Aws dynamodb describe-table --table-name $TABLA --query "Table.LatestStreamArn" --output text
if (Vacio $STREAM) { Falla "La tabla $TABLA no tiene Stream. Actívalo con NEW_IMAGE" }
$MAPEO = aws lambda list-event-source-mappings --function-name $LAMBDA --event-source-arn $STREAM --query "EventSourceMappings[0].UUID" --output text
if (Vacio $MAPEO) {
    Ejecutar-Aws lambda create-event-source-mapping --function-name $LAMBDA --event-source-arn $STREAM `
        --starting-position LATEST --batch-size 100 --maximum-batching-window-in-seconds 2 `
        --maximum-record-age-in-seconds 21600 --maximum-retry-attempts=-1 | Out-Null
    Ok "Conectada al Stream de $TABLA"
} else { Ok "Ya conectada al Stream de $TABLA" }

Paso "Comprobando el servidor"
Esperar-Salud $API_URL | Out-Null
Mostrar-Direcciones
Write-Host " Para apagar el servidor al terminar: .\desplegar_dashboard_aws.ps1 -Accion detener" -ForegroundColor Yellow
