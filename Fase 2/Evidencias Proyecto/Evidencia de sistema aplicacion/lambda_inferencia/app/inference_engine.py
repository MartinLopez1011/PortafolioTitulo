import joblib
import numpy as np
import pandas as pd
import keras
from .config import (
    PATH_DIAGNOSTICO,
    PATH_AE_KERAS,
    PATH_AE_CONFIG,
    PATH_PREDICTIVO,
    ESTADOS_ACTIVOS
)

class MolinoInferenceEngine:
    def __init__(self):
        # 1. Diagnóstico (config_modelo.joblib)
        diag = joblib.load(PATH_DIAGNOSTICO)
        self.mod_etapa1 = diag["modelo_etapa1"]
        self.mod_etapa2 = diag["modelo_etapa2"]
        self.le_fallas = diag["label_encoder_fallas"]
        self.scaler_diag = diag["scaler"]
        self.features_31 = diag["features"]

        # 2. Vigilancia (autoencoder_molino_config.joblib + autoencoder_molino_QLA.keras)
        vig = joblib.load(PATH_AE_CONFIG)
        self.scaler_vig = vig["scaler"]
        self.umbral_vig = float(vig["umbral"])
        self.ae_model = keras.models.load_model(PATH_AE_KERAS)

        # 3. Predicción (modelo_predictivo.joblib)
        pred = joblib.load(PATH_PREDICTIVO)
        self.modelos_ml = pred["modelos"]
        self.umbrales_ml = pred["umbrales"]
        self.reglas_tendencia = pred["tendencia"]
        self.acciones = pred["acciones"]
        self.referencias_normal = pred["referencias_normal"]
        self.features_80 = pred["features_tabulares"]

    def _preparar_31_features(self, payload_minuto: dict) -> pd.DataFrame:
        df = pd.DataFrame([payload_minuto])
        if "es_plastomerico" not in df.columns:
            df["es_plastomerico"] = int(df.get("TIPO_asfalto", pd.Series(["Convencional"])).iloc[0] == "Plastomerico")
        if "en_limpieza" not in df.columns:
            df["en_limpieza"] = int(df.get("ESTADO_operacion", pd.Series(["Produccion"])).iloc[0] == "Limpieza")
        return df[self.features_31]

    def ejecutar_tiempo_real(self, payload_minuto: dict) -> dict:
        estado = payload_minuto.get("ESTADO_operacion", "Produccion")
        if estado not in ESTADOS_ACTIVOS:
            return {"monitoreo_activo": False, "estado_operacion": estado}

        X_31 = self._preparar_31_features(payload_minuto)

        # Vigilancia (Autoencoder)
        X_vig = self.scaler_vig.transform(X_31)
        X_rec = self.ae_model.predict(X_vig, verbose=0)
        err_sensores = np.square(X_vig - X_rec)[0]
        mse = float(np.mean(err_sensores))
        alerta_ae = mse > self.umbral_vig

        top_idx = np.argsort(err_sensores)[::-1][:3]
        top_sensores = [
            {"sensor": self.features_31[i], "error_cuadratico": round(float(err_sensores[i]), 4)}
            for i in top_idx
        ]

        # Diagnóstico (LightGBM Etapa 1 -> Etapa 2)
        X_diag = self.scaler_diag.transform(X_31)
        es_anomalia = int(self.mod_etapa1.predict(X_diag)[0])
        prob_anomalia = float(self.mod_etapa1.predict_proba(X_diag)[0, 1])

        falla_detectada = "Normal"
        confianza = 0.0
        if es_anomalia == 1:
            clase_idx = self.mod_etapa2.predict(X_diag)[0]
            probs_e2 = self.mod_etapa2.predict_proba(X_diag)[0]
            confianza = float(np.max(probs_e2))
            falla_detectada = str(self.le_fallas.inverse_transform([clase_idx])[0])

        return {
            "monitoreo_activo": True,
            "estado_operacion": estado,
            "diagnostico": {
                "anomalia_confirmada": bool(es_anomalia),
                "probabilidad_etapa1": round(prob_anomalia, 4),
                "falla": falla_detectada,
                "confianza_etapa2": round(confianza, 4),
                "accion": self.acciones.get(falla_detectada) if es_anomalia else None
            },
            "vigilancia_autoencoder": {
                "alerta_anomalia_nueva": bool(alerta_ae),
                "mse": round(mse, 4),
                "umbral": round(self.umbral_vig, 4),
                "indice_salud_ratio": round(mse / self.umbral_vig, 2),
                "sensores_mayor_desviacion": top_sensores
            }
        }

    def ejecutar_predictivo(self, payload_80_features: dict) -> dict:
        X_80 = pd.DataFrame([payload_80_features])[self.features_80]
        alertas = []

        # 9 Modelos LightGBM (3 fallas x 3 horizontes: '24 h', '5 días', '15 días')
        for (falla, horizonte), modelo in self.modelos_ml.items():
            prob = float(modelo.predict_proba(X_80)[0, 1])
            umbral = float(self.umbrales_ml[(falla, horizonte)])
            if prob >= umbral:
                alertas.append({
                    "metodo": "LightGBM_MultiHorizonte",
                    "falla": falla,
                    "horizonte": horizonte,
                    "probabilidad": round(prob, 4),
                    "umbral": round(umbral, 4),
                    "accion_recomendada": self.acciones.get(falla, "")
                })

        # 4 Reglas físicas de tendencia
        for falla, regla in self.reglas_tendencia.items():
            col = regla.get("variable")
            lim = regla.get("umbral")
            direc = regla.get("direccion", "mayor")
            if col in X_80.columns:
                val = float(X_80[col].iloc[0])
                activa = (val >= lim) if direc == "mayor" else (val <= lim)
                if activa:
                    alertas.append({
                        "metodo": "Regla_Tendencia",
                        "falla": falla,
                        "horizonte": regla.get("horizonte", "Preventivo"),
                        "variable": col,
                        "valor_actual": round(val, 4),
                        "umbral": lim,
                        "accion_recomendada": self.acciones.get(falla, "")
                    })

        return {"total_alertas": len(alertas), "alertas_preventivas": alertas}