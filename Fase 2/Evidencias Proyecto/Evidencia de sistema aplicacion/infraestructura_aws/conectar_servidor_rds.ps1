# ==============================================================================
# Conecta el servidor EC2 "qla-servidor" (contenedor Docker "qla") a la RDS y deja
# el simulador listo para publicar en IoT Core. Ejecutar DESPUES de:
#   crear_rds.ps1  +  ejecutar_sql.py bd_mantpred_v4_1_completo.sql  +  crear_admin.py
#
#   .\conectar_servidor_rds.ps1
#
# Que hace:
#   1. Enciende la EC2 si esta detenida y apunta API Gateway a su IP actual.
#   2. Da al rol del servidor permiso para reiniciar la Lambda (boton "Ir a").
#   3. Sube el dataset del simulador al bucket de la Lambda (solo si falta).
#   4. Por SSM (sin SSH), actualiza /opt/qla/Backend/.env:
#        MODO_DEMO=0, DATABASE_URL, IOT_ENDPOINT, AWS_REGION
#      y vuelve a crear el contenedor "qla" con la misma imagen.
#   5. Muestra la respuesta de /api/salud (debe decir "base_de_datos": "ok").
# Ningun secreto se muestra en pantalla.
# ==============================================================================
param(
    [string]$Region = "us-east-2",
    [string]$ArchivoEnv = "$HOME\qla_rds_aws.env",
    [string]$Lambda = "qla-molino-inferencia",
    [string]$Api = "qla-dashboard"
)

$ErrorActionPreference = "Continue"
$env:AWS_DEFAULT_REGION = $Region
$env:AWS_PAGER = ""
$TMP = Join-Path $env:TEMP "qla_conectar"
New-Item -ItemType Directory -Force -Path $TMP | Out-Null

function Paso($t) { Write-Host "`n>> $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "   [OK] $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   [AVISO] $t" -ForegroundColor Yellow }
function Falla($t) { Write-Host "   [ERROR] $t" -ForegroundColor Red; exit 1 }
function Vacio($v) { return (-not $v) -or ($v -eq "None") }
function Escribir-Utf8($ruta, $texto) {
    [IO.File]::WriteAllText($ruta, $texto.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
}

Paso "Leyendo la conexion a la base de $ArchivoEnv (no se muestra)"
if (-not (Test-Path $ArchivoEnv)) { Falla "No existe $ArchivoEnv. Ejecuta antes crear_rds.ps1" }
$dbUrl = $null
foreach ($l in Get-Content $ArchivoEnv) {
    if ($l -match "^\s*DATABASE_URL\s*=\s*(.+)$") { $dbUrl = $Matches[1].Trim() }
}
if (-not $dbUrl) { Falla "$ArchivoEnv no tiene DATABASE_URL (la RDS no termino de crearse)" }
Ok "Conexion leida"

Paso "Servidor EC2 qla-servidor"
$iid = aws ec2 describe-instances --filters "Name=tag:Name,Values=qla-servidor" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query "Reservations[0].Instances[0].InstanceId" --output text
if (Vacio $iid) { Falla "No existe la EC2 qla-servidor en $Region" }
$estado = aws ec2 describe-instances --instance-ids $iid --query "Reservations[0].Instances[0].State.Name" --output text
if ($estado -ne "running") {
    if ($estado -eq "stopping") { aws ec2 wait instance-stopped --instance-ids $iid }
    aws ec2 start-instances --instance-ids $iid | Out-Null
    Write-Host "   Encendiendo $iid ..."
    aws ec2 wait instance-running --instance-ids $iid
}
$ip = aws ec2 describe-instances --instance-ids $iid --query "Reservations[0].Instances[0].PublicIpAddress" --output text
Ok "Servidor $iid encendido (IP $ip)"

$apiId = aws apigatewayv2 get-apis --query "Items[?Name=='$Api'].ApiId | [0]" --output text
if (-not (Vacio $apiId)) {
    $ints = (aws apigatewayv2 get-integrations --api-id $apiId --query "Items[].IntegrationId" --output text) -split "\s+" | Where-Object { $_ }
    foreach ($int in $ints) {
        $uri = aws apigatewayv2 get-integration --api-id $apiId --integration-id $int --query IntegrationUri --output text
        if ($uri -like "*{proxy}*") { $nueva = "http://$ip/{proxy}" } else { $nueva = "http://$ip/" }
        aws apigatewayv2 update-integration --api-id $apiId --integration-id $int --integration-uri $nueva | Out-Null
    }
    $urlApi = "https://$apiId.execute-api.$Region.amazonaws.com"
    Ok "API Gateway apunta a la IP actual: $urlApi"
} else { Aviso "No se encontro el API Gateway $Api" }

Paso "Permiso del servidor para reiniciar la Lambda (boton 'Ir a' del simulador)"
$perfilArn = aws ec2 describe-instances --instance-ids $iid --query "Reservations[0].Instances[0].IamInstanceProfile.Arn" --output text
if (Vacio $perfilArn) {
    Aviso "La EC2 no tiene perfil IAM; el simulador no podra publicar en IoT Core"
} else {
    $perfil = $perfilArn.Split("/")[-1]
    $rol = aws iam get-instance-profile --instance-profile-name $perfil --query "InstanceProfile.Roles[0].RoleName" --output text
    $cuenta = aws sts get-caller-identity --query Account --output text
    $politica = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["lambda:GetFunctionConfiguration", "lambda:UpdateFunctionConfiguration"],
    "Resource": "arn:aws:lambda:${Region}:${cuenta}:function:${Lambda}"
  }]
}
"@
    $archPol = Join-Path $TMP "politica_lambda.json"
    Escribir-Utf8 $archPol $politica
    aws iam put-role-policy --role-name $rol --policy-name qla-simulador-reinicio-lambda --policy-document "file://$archPol" | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "Politica agregada al rol $rol" } else { Aviso "No se pudo agregar la politica al rol $rol" }
}

Paso "Dataset del simulador en el bucket de la Lambda"
$bucket = aws lambda get-function-configuration --function-name $Lambda --query "Environment.Variables.S3_BUCKET" --output text
if (Vacio $bucket) { Falla "La Lambda $Lambda no tiene la variable S3_BUCKET" }
aws s3 ls "s3://$bucket/despliegue/Dataset_Molino_QLA_Realista.zip" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Ok "Ya estaba en s3://$bucket/despliegue/"
} else {
    $dataset = Join-Path $PSScriptRoot "..\Dataset Simulado\Dataset_Molino_QLA_Realista.zip"
    if (-not (Test-Path $dataset)) { Falla "No se encontro $dataset" }
    aws s3 cp $dataset "s3://$bucket/despliegue/Dataset_Molino_QLA_Realista.zip" --only-show-errors
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo subir el dataset" }
    Ok "Dataset subido a s3://$bucket/despliegue/ (34 MB)"
}

Paso "Endpoint de IoT Core"
$iot = aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text
if (Vacio $iot) { Falla "No se pudo obtener el endpoint de IoT Core" }
Ok $iot

Paso "Esperando que el agente SSM del servidor este en linea"
$enLinea = $false
for ($i = 0; $i -lt 40; $i++) {
    $ping = aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$iid" --query "InstanceInformationList[0].PingStatus" --output text 2>$null
    if ($ping -eq "Online") { $enLinea = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $enLinea) { Falla "El servidor no responde por SSM (espera 1 minuto y vuelve a ejecutar el script)" }
Ok "SSM en linea"

Paso "Actualizando el .env del servidor y recreando el contenedor (no se muestran secretos)"
$bash = @"
#!/bin/bash
set -uo pipefail
F=/opt/qla/Backend/.env
mkdir -p /opt/qla/Backend
touch `$F
poner() { if grep -q "^`$1=" `$F; then sed -i "s|^`$1=.*|`$1=`$2|" `$F; else echo "`$1=`$2" >> `$F; fi; }
poner MODO_DEMO 0
poner DATABASE_URL '$dbUrl'
poner IOT_ENDPOINT '$iot'
poner AWS_REGION '$Region'
poner AWS_DEFAULT_REGION '$Region'
grep -q '^JWT_SECRET=' `$F || echo "JWT_SECRET=`$(openssl rand -hex 32)" >> `$F
grep -q '^CLAVE_INGESTA=' `$F || echo "CLAVE_INGESTA=`$(openssl rand -hex 24)" >> `$F
chmod 600 `$F
IMG=`$(cat /opt/qla/imagen_actual 2>/dev/null || docker inspect --format '{{.Config.Image}}' qla 2>/dev/null || true)
if [ -z "`$IMG" ]; then echo "SIN_IMAGEN: ejecuta el workflow CD (componente backend) de GitHub"; rm -f /tmp/qla_rds.sh; exit 0; fi
REG=`${IMG%%/*}
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin `$REG >/dev/null 2>&1
docker rm -f qla >/dev/null 2>&1 || true
docker run -d --name qla --restart always -p 80:8000 --env-file `$F -e AWS_DEFAULT_REGION=$Region -e AWS_REGION=$Region --log-driver json-file --log-opt max-size=20m --log-opt max-file=3 "`$IMG" >/dev/null
for i in `$(seq 1 30); do R=`$(curl -s http://127.0.0.1/api/salud); [ -n "`$R" ] && break; sleep 3; done
echo "SALUD: `$R"
rm -f /tmp/qla_rds.sh
"@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bash.Replace("`r`n", "`n")))
$params = @{ commands = @("echo $b64 | base64 -d > /tmp/qla_rds.sh", "bash /tmp/qla_rds.sh") } | ConvertTo-Json -Compress
$archParams = Join-Path $TMP "params.json"
Escribir-Utf8 $archParams $params
$cmd = aws ssm send-command --instance-ids $iid --document-name AWS-RunShellScript --comment "QLA: conectar a RDS" --timeout-seconds 600 --parameters "file://$archParams" --query "Command.CommandId" --output text
Remove-Item $archParams -ErrorAction SilentlyContinue
if (Vacio $cmd) { Falla "No se pudo enviar el comando por SSM" }
Write-Host "   Ejecutando en el servidor (1 a 2 minutos)..."
$est = "Pending"
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    $est = aws ssm get-command-invocation --command-id $cmd --instance-id $iid --query "Status" --output text 2>$null
    if ($est -and $est -notin @("Pending", "InProgress", "Delayed")) { break }
}
$salida = aws ssm get-command-invocation --command-id $cmd --instance-id $iid --query "StandardOutputContent" --output text
Write-Host "   Estado: $est"
Write-Host "   $salida"

if ($salida -match '"base_de_datos":"ok"') {
    Ok "El servidor esta conectado a la RDS (sin modo demo)"
    if ($urlApi) { Write-Host "`n Dashboard: $urlApi" -ForegroundColor Green }
} elseif ($salida -match "SIN_IMAGEN") {
    Aviso "El .env quedo listo; falta desplegar la imagen con el workflow CD (componente backend)"
} else {
    Aviso "Revisa la respuesta de arriba. Si dice modo_demostracion o 503, avisame con ese texto."
}
