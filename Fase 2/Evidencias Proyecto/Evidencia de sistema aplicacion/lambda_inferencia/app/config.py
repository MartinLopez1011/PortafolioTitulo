import os
from pathlib import Path

# En AWS Lambda con Docker, el directorio raíz suele ser /var/task
BASE_DIR = Path(os.environ.get("LAMBDA_TASK_ROOT", Path(__file__).resolve().parent.parent))
ARTIFACTS_DIR = BASE_DIR / "artifacts"

PATH_DIAGNOSTICO = ARTIFACTS_DIR / "config_modelo.joblib"
PATH_AE_KERAS = ARTIFACTS_DIR / "autoencoder_molino_QLA.keras"
PATH_AE_CONFIG = ARTIFACTS_DIR / "autoencoder_molino_config.joblib"
PATH_PREDICTIVO = ARTIFACTS_DIR / "modelo_predictivo.joblib"

ESTADOS_ACTIVOS = {"Produccion", "Limpieza"}