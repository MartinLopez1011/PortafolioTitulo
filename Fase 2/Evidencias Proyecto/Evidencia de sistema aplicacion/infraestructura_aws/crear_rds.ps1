# ==============================================================================
# Crea la base Amazon RDS PostgreSQL "qla-mantpred" en la misma red (VPC) que el
# servidor EC2 "qla-servidor" y deja la conexion en un archivo FUERA del repositorio.
#
#   .\crear_rds.ps1                       # us-east-2 por defecto
#   .\crear_rds.ps1 -Region us-east-1
#
# Que hace:
#   1. Ubica la VPC y el grupo de seguridad del servidor EC2.
#   2. Crea el grupo de seguridad "qla-rds-sg": puerto 5432 abierto SOLO para el
#      servidor (por grupo de seguridad) y para la IP publica de este computador.
#   3. Genera una clave aleatoria (no se muestra en pantalla).
#   4. Crea la RDS: PostgreSQL 16, db.t3.micro, 20 GB gp3, cifrada, 1 dia de respaldo.
#   5. Espera a que este disponible (5 a 15 min) y escribe DATABASE_URL en
#      $HOME\qla_rds_aws.env  (NO subir a Git ni compartir).
#
# Despues:  cd "..\Base de Datos"
#           python ejecutar_sql.py bd_mantpred_v4_1_completo.sql --env "$HOME\qla_rds_aws.env"
#           python crear_admin.py --env "$HOME\qla_rds_aws.env"
# ==============================================================================
param(
    [string]$Region = "us-east-2",
    [string]$Instancia = "qla-mantpred",
    [string]$Usuario = "qla_admin",
    [string]$ArchivoEnv = "$HOME\qla_rds_aws.env"
)

$ErrorActionPreference = "Continue"
$env:AWS_DEFAULT_REGION = $Region
$env:AWS_PAGER = ""

function Paso($t) { Write-Host "`n>> $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "   [OK] $t" -ForegroundColor Green }
function Falla($t) { Write-Host "   [ERROR] $t" -ForegroundColor Red; exit 1 }
function Vacio($v) { return (-not $v) -or ($v -eq "None") }

Paso "Comprobando credenciales"
$cuenta = aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0) { Falla "Las credenciales de AWS no funcionan (revisa $HOME\.aws\credentials)" }
Ok "Cuenta $cuenta, region $Region"

aws rds describe-db-instances --db-instance-identifier $Instancia 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Falla "La RDS '$Instancia' ya existe. No se crea otra (si perdiste la clave, cambiala desde la consola: RDS > Modificar)."
}

Paso "Ubicando la red del servidor EC2 qla-servidor"
$iid = aws ec2 describe-instances --filters "Name=tag:Name,Values=qla-servidor" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query "Reservations[0].Instances[0].InstanceId" --output text
if (Vacio $iid) { Falla "No existe la EC2 qla-servidor en $Region. Ejecuta antes el workflow 'CD' de GitHub." }
$vpc = aws ec2 describe-instances --instance-ids $iid --query "Reservations[0].Instances[0].VpcId" --output text
$sgWeb = aws ec2 describe-instances --instance-ids $iid --query "Reservations[0].Instances[0].SecurityGroups[0].GroupId" --output text
Ok "Servidor $iid en VPC $vpc (grupo $sgWeb)"

Paso "Grupo de seguridad de la base (qla-rds-sg)"
$miIp = (Invoke-RestMethod -Uri "https://checkip.amazonaws.com" -TimeoutSec 15).ToString().Trim()
$sgRds = aws ec2 describe-security-groups --filters "Name=group-name,Values=qla-rds-sg" "Name=vpc-id,Values=$vpc" --query "SecurityGroups[0].GroupId" --output text
if (Vacio $sgRds) {
    $sgRds = aws ec2 create-security-group --group-name qla-rds-sg --description "PostgreSQL QLA: solo el servidor y el administrador" --vpc-id $vpc --query GroupId --output text
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo crear el grupo de seguridad" }
}
aws ec2 authorize-security-group-ingress --group-id $sgRds --protocol tcp --port 5432 --source-group $sgWeb 2>$null | Out-Null
aws ec2 authorize-security-group-ingress --group-id $sgRds --protocol tcp --port 5432 --cidr "$miIp/32" 2>$null | Out-Null
Ok "Puerto 5432 abierto solo para el servidor y para tu IP ($miIp)"

Paso "Generando la clave de la base (no se muestra)"
$letras = [char[]]"abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
$bytes = New-Object byte[] 28
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$clave = -join ($bytes | ForEach-Object { $letras[$_ % $letras.Length] })
# Se guarda de inmediato, por si el script se interrumpe mientras se crea la base
Set-Content -Path $ArchivoEnv -Value "RDS_CLAVE_PENDIENTE=$clave" -Encoding ASCII
Ok "Clave guardada en $ArchivoEnv"

Paso "Creando la RDS $Instancia (PostgreSQL 16, db.t3.micro, 20 GB)"
$version = aws rds describe-db-engine-versions --engine postgres --engine-version 16 --default-only --query "DBEngineVersions[0].EngineVersion" --output text 2>$null
$argVersion = @()
if (-not (Vacio $version)) { $argVersion = @("--engine-version", $version) }
aws rds create-db-instance --db-instance-identifier $Instancia --engine postgres @argVersion `
    --db-instance-class db.t3.micro --allocated-storage 20 --storage-type gp3 --storage-encrypted `
    --master-username $Usuario --master-user-password $clave `
    --vpc-security-group-ids $sgRds --publicly-accessible --no-multi-az `
    --backup-retention-period 1 --no-deletion-protection `
    --tags Key=Proyecto,Value=QLA-mantenimiento-predictivo | Out-Null
if ($LASTEXITCODE -ne 0) { Falla "AWS rechazo la creacion de la base (revisa el mensaje de arriba)" }
Ok "Creacion iniciada (version $version)"

Paso "Esperando a que la base este disponible (5 a 15 minutos; no cierres esta ventana)"
aws rds wait db-instance-available --db-instance-identifier $Instancia
if ($LASTEXITCODE -ne 0) {
    aws rds wait db-instance-available --db-instance-identifier $Instancia
}
$endpoint = aws rds describe-db-instances --db-instance-identifier $Instancia --query "DBInstances[0].Endpoint.Address" --output text
if (Vacio $endpoint) { Falla "La base aun no tiene direccion. Vuelve a revisar en unos minutos en la consola de RDS." }

Set-Content -Path $ArchivoEnv -Value "DATABASE_URL=postgresql://${Usuario}:${clave}@${endpoint}:5432/postgres?sslmode=require" -Encoding ASCII
Ok "Base disponible en $endpoint"
Ok "Conexion guardada en $ArchivoEnv (no la subas a Git ni la compartas)"

Write-Host "`nSiguiente paso, desde la carpeta 'Base de Datos':" -ForegroundColor Yellow
Write-Host "   python ejecutar_sql.py bd_mantpred_v4_1_completo.sql --env `"$ArchivoEnv`""
Write-Host "   python crear_admin.py --env `"$ArchivoEnv`""
