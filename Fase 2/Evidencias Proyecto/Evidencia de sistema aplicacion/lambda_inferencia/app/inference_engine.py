import datetime as dt
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

# ============================================================================
# CONTRATO CANÓNICO DE ENTRADA DE MODELOS (31 VARIABLES -> 11 -> 80)
# ============================================================================
SENSORES_29: list[str] = [
    "TEM_son_betum_in",
    "RES_son_betum_in",
    "VOLT_son_betum_in",
    "AMP_son_betum_in",
    "AMP_cau_betum_in",
    "FRE_cau_betum_in",
    "AMP_eco_betum_dep",
    "EST_niv_betum_dep",
    "TEM_son_solucion_in",
    "RES_son_solucion_in",
    "AMP_son_solucion_in",
    "AMP_cau_solucion_in",
    "FRE_cau_solucion_in",
    "AMP_eco_solucion_dep",
    "TEM_son_emulsion_out",
    "RES_son_emulsion_out",
    "AMP_cau_emulsion_out",
    "FRE_cau_emulsion_out",
    "AMP_eco_emulsion_dep",
    "RPM_motor_molino",
    "FRE_vfd_motor_molino",
    "AMP_vfd_motor_molino",
    "TOR_vfd_motor_molino",
    "VIB_vel_motor_molino",
    "AMP_vib_motor_molino",
    "CAU_bomba_lpm",
    "PRE_dif_filtro_bar",
    "TEM_emulsion_molino_out",
    "PRE_intercambiador_bar",
]

FEATURES_31_CANONICAS: list[str] = SENSORES_29 + ["es_plastomerico", "en_limpieza"]

# Las 11 variables que el Modelo 3 refactoriza a partir de las 31 de entrada:
# 10 sensores continuos para desviaciones + EST_niv_betum_dep (EST_radar)
SENSORES_10_PREDICTIVO: list[str] = [
    "TEM_son_betum_in",
    "AMP_eco_betum_dep",
    "VOLT_son_betum_in",
    "AMP_cau_solucion_in",
    "AMP_vfd_motor_molino",
    "TOR_vfd_motor_molino",
    "VIB_vel_motor_molino",
    "PRE_dif_filtro_bar",
    "PRE_intercambiador_bar",
    "CAU_bomba_lpm",
]
VARIABLES_11_MODELO3: list[str] = SENSORES_10_PREDICTIVO + ["EST_niv_betum_dep"]

SOLO_PRODUCCION_PREDICTIVO: list[str] = [
    "AMP_vfd_motor_molino",
    "TOR_vfd_motor_molino",
    "VIB_vel_motor_molino",
    "PRE_dif_filtro_bar",
    "PRE_intercambiador_bar",
    "CAU_bomba_lpm",
]

COLUMNA_TENDENCIA_POR_FALLA: dict[str, str] = {
    "Cortocircuito_Transmisor_Caudal_Sol": "dev_AMP_cau_solucion_in",
    "Falla_Electrica_PT100_Betun": "dev_VOLT_son_betum_in",
    "Ensuciamiento_Intercambiador": "dev_PRE_intercambiador_bar",
    "Desgaste_Rodamientos_Molino": "dev_VIB_vel_motor_molino",
    "Filtro_Obstruido": "dev_PRE_dif_filtro_bar",
}


class MolinoInferenceEngine:
    def __init__(self):
        # 1. Diagnóstico (Modelo 1: config_modelo.joblib -> 31 variables)
        diag = joblib.load(PATH_DIAGNOSTICO)
        self.mod_etapa1 = diag["modelo_etapa1"]
        self.mod_etapa2 = diag["modelo_etapa2"]
        self.le_fallas = diag["label_encoder_fallas"]
        self.scaler_diag = diag["scaler"]
        self.features_31 = list(diag.get("features", FEATURES_31_CANONICAS))

        # 2. Vigilancia (Modelo 2: autoencoder_molino_config.joblib + .keras -> 31 variables)
        vig = joblib.load(PATH_AE_CONFIG)
        self.scaler_vig = vig["scaler"]
        self.umbral_vig = float(vig["umbral"])
        self.features_ae_31 = list(vig.get("features", self.features_31))
        self.ae_model = keras.models.load_model(PATH_AE_KERAS)

        # 3. Predicción (Modelo 3: modelo_predictivo.joblib -> 31 -> 11 -> 80 variables)
        pred = joblib.load(PATH_PREDICTIVO)
        self.pq = pred
        self.familia_pred = pred.get("familia", "LightGBM")
        self.fallas_ml = pred.get(
            "fallas_ml",
            ["Sobrecarga_Motor_Por_Asfalto_Frio", "Filtro_Obstruido", "Advertencia_Radar_Sucio_Betun"],
        )
        self.fallas_tendencia = pred.get(
            "fallas_tendencia",
            [
                "Cortocircuito_Transmisor_Caudal_Sol",
                "Falla_Electrica_PT100_Betun",
                "Ensuciamiento_Intercambiador",
                "Desgaste_Rodamientos_Molino",
            ],
        )
        self.horizontes = pred.get("horizontes", {"24 h": 24, "5 días": 120, "15 días": 360})
        self.modelos_ml = pred["modelos"]
        self.umbrales_ml = pred["umbrales"]
        self.reglas_tendencia = pred.get("tendencia", {})
        self.acciones = pred.get("acciones", {})
        self.referencias_normal = pred["referencias_normal"]
        self.sensores_10 = list(pred.get("sensores", SENSORES_10_PREDICTIVO))
        self.solo_produccion = list(pred.get("solo_produccion", SOLO_PRODUCCION_PREDICTIVO))
        self.intervenciones = pred.get("intervenciones", {
            "filtro": ("filtro", "limpieza de filtro"),
            "radar": ("radar", "antena del radar"),
            "caldera": ("caldera", "mantención de caldera"),
            "intercambiador": ("intercambiador", "intercambiador"),
            "caudalimetro": ("caudalímetro", "transmisor de caudal"),
            "pt100": ("pt100", "borneras"),
            "rodamientos": ("rodamientos", "cambio preventivo de rodamientos"),
        })
        self.features_80 = list(pred["features_tabulares"])

    # ========================================================================
    # PREPARACIÓN DE LAS 31 VARIABLES DE ENTRADA (COMÚN A MODELOS 1, 2 Y 3)
    # ========================================================================
    @staticmethod
    def _normalizar_timestamp_epoch(ts_val) -> int:
        if ts_val is None:
            return int(dt.datetime.now(dt.timezone.utc).timestamp())
        if isinstance(ts_val, (int, float, np.number)):
            val = float(ts_val)
            if np.isnan(val) or np.isinf(val):
                return int(dt.datetime.now(dt.timezone.utc).timestamp())
            return int(val / 1000.0) if val > 1e11 else int(val)
        try:
            s = str(ts_val).strip()
            if s.isdigit():
                val = int(s)
                return int(val / 1000) if val > 10**11 else val
            parsed = pd.to_datetime(s, utc=True)
            return int(parsed.timestamp())
        except Exception:
            return int(dt.datetime.now(dt.timezone.utc).timestamp())

    @staticmethod
    def _normalizar_estado_y_tipo(estado_raw: str, tipo_raw: str, en_limp: int, es_plasto: int) -> tuple[str, str]:
        mapa_estados = {
            "produccion": "Produccion",
            "producción": "Produccion",
            "limpieza": "Limpieza",
            "detenido": "Detenida",
            "detenida": "Detenida",
            "preparacion": "Preparacion",
            "preparación": "Preparacion",
            "espera": "Espera",
            "mantenimiento": "Mantenimiento",
        }
        mapa_tipos = {
            "convencional": "Convencional",
            "plastomerico": "Plastomerico",
            "plastomérico": "Plastomerico",
            "ninguno": "Ninguno",
        }
        est_key = str(estado_raw or "").strip().lower()
        tip_key = str(tipo_raw or "").strip().lower()

        if est_key in mapa_estados:
            estado_op = mapa_estados[est_key]
        else:
            estado_op = "Limpieza" if en_limp == 1 else "Produccion"

        if tip_key in mapa_tipos:
            tipo_asf = mapa_tipos[tip_key]
        elif tip_key.startswith("plasto"):
            tipo_asf = "Plastomerico"
        else:
            tipo_asf = "Plastomerico" if es_plasto == 1 else "Convencional"

        return estado_op, tipo_asf

    def Normalizar_Entrada_31(self, payload_minuto: dict) -> dict:
        """
        Garantiza que cualquier lectura entrante (plana o anidada en 'lectura_actual'/'lecturas')
        contenga las 31 variables canónicas (29 sensores + es_plastomerico + en_limpieza)
        arregladas y listas para los 3 modelos, preservando ESTADO_operacion, TIPO_asfalto y timestamp.
        """
        raiz = dict(payload_minuto) if isinstance(payload_minuto, dict) else {}
        anidado = raiz.get("lectura_actual") or raiz.get("lecturas")
        if isinstance(anidado, dict):
            datos = {**raiz, **anidado}
        else:
            datos = raiz

        raw_estado = datos.get("ESTADO_operacion") or datos.get("estado_operacion")
        raw_tipo = datos.get("TIPO_asfalto") or datos.get("tipo_asfalto")

        es_plasto = int(
            datos.get(
                "es_plastomerico",
                1 if str(raw_tipo or "Convencional").strip().lower().startswith("plasto") else 0,
            )
        )
        en_limp = int(
            datos.get(
                "en_limpieza",
                1 if str(raw_estado or "Produccion").strip().lower() == "limpieza" else 0,
            )
        )

        estado_op, tipo_asf = self._normalizar_estado_y_tipo(raw_estado, raw_tipo, en_limp, es_plasto)
        es_plasto = 1 if tipo_asf == "Plastomerico" else int(bool(es_plasto))
        en_limp = 1 if estado_op == "Limpieza" else 0

        limpio = {
            "timestamp": self._normalizar_timestamp_epoch(datos.get("timestamp")),
            "ESTADO_operacion": estado_op,
            "TIPO_asfalto": tipo_asf,
            "es_plastomerico": es_plasto,
            "en_limpieza": en_limp,
        }
        for s in SENSORES_29:
            val = datos.get(s, 0.0)
            try:
                fval = float(val) if val is not None else 0.0
                limpio[s] = 0.0 if (np.isnan(fval) or np.isinf(fval)) else fval
            except (ValueError, TypeError):
                limpio[s] = 0.0
        return limpio

    def _preparar_31_features(self, payload_minuto: dict) -> pd.DataFrame:
        registro_31 = self.Normalizar_Entrada_31(payload_minuto)
        df = pd.DataFrame([registro_31])
        return df[self.features_31].astype("float32")

    # ========================================================================
    # MODELOS 1 Y 2: DIAGNÓSTICO (LIGHTGBM) Y VIGILANCIA (AUTOENCODER) CON 31 VARS
    # ========================================================================
    def ejecutar_tiempo_real(self, payload_minuto: dict) -> dict:
        registro_31 = self.Normalizar_Entrada_31(payload_minuto)
        estado = registro_31["ESTADO_operacion"]
        if estado not in ESTADOS_ACTIVOS:
            return {"monitoreo_activo": False, "estado_operacion": estado}

        X_31 = pd.DataFrame([registro_31])[self.features_31].astype("float32")
        X_ae_31 = pd.DataFrame([registro_31])[self.features_ae_31].astype("float32")

        # Modelo 2: Vigilancia (Autoencoder recibe las 31 variables escaladas)
        X_vig = self.scaler_vig.transform(X_ae_31).astype("float32")
        X_rec = self.ae_model.predict(X_vig, verbose=0)
        err_sensores = np.square(X_vig - X_rec)[0]
        mse = float(np.mean(err_sensores))
        alerta_ae = mse > self.umbral_vig

        top_idx = np.argsort(err_sensores)[::-1][:3]
        top_sensores = [
            {"sensor": self.features_ae_31[i], "error_cuadratico": round(float(err_sensores[i]), 4)}
            for i in top_idx
        ]

        # Modelo 1: Diagnóstico Jerárquico (LightGBM Etapa 1 -> Etapa 2 recibe las 31 variables escaladas)
        X_diag = self.scaler_diag.transform(X_31).astype("float32")
        X_diag_df = pd.DataFrame(X_diag, columns=self.features_31)
        es_anomalia = int(self.mod_etapa1.predict(X_diag_df)[0])
        prob_anomalia = float(self.mod_etapa1.predict_proba(X_diag_df)[0, 1])

        falla_detectada = "Normal"
        confianza = 0.0
        if es_anomalia == 1:
            clase_idx = self.mod_etapa2.predict(X_diag_df)[0]
            probs_e2 = self.mod_etapa2.predict_proba(X_diag_df)[0]
            confianza = float(np.max(probs_e2))
            falla_detectada = str(self.le_fallas.inverse_transform([clase_idx])[0])

        umbral_seguro = max(float(self.umbral_vig), 1e-9)
        return {
            "monitoreo_activo": True,
            "estado_operacion": estado,
            "tipo_asfalto": registro_31["TIPO_asfalto"],
            "variables_entrada_31": len(self.features_31),
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
                "indice_salud_ratio": round(mse / umbral_seguro, 2),
                "sensores_mayor_desviacion": top_sensores
            }
        }

    # ========================================================================
    # MODELO 3: REFACTORIZACIÓN DE 31 VARIABLES -> 11 VARIABLES -> 80 FEATURES
    # ========================================================================
    def _resumen_horario_11_variables(self, df_31: pd.DataFrame) -> pd.DataFrame:
        """
        Toma un DataFrame con las 31 variables de entrada, selecciona y refactoriza
        las 11 variables clave del Modelo 3 (10 sensores de desviación por modo + EST_niv_betum_dep)
        y construye la tabla horaria H (13 señales base + 3 acumuladores de desgaste).
        """
        dfm = df_31.copy()

        # Asegurar timestamp como datetime UTC sin tz para indexación horaria limpia
        if np.issubdtype(dfm["timestamp"].dtype, np.number):
            ts = pd.to_datetime(dfm["timestamp"], unit="s", utc=True).dt.tz_localize(None)
        else:
            ts = pd.to_datetime(dfm["timestamp"], utc=True).dt.tz_localize(None)
        dfm["timestamp"] = ts

        # Reconstruir ESTADO_operacion y TIPO_asfalto desde las 31 variables si faltan
        if "ESTADO_operacion" not in dfm.columns:
            en_limp = dfm.get("en_limpieza", pd.Series(0, index=dfm.index)).astype(int)
            dfm["ESTADO_operacion"] = np.where(en_limp == 1, "Limpieza", "Produccion")
        else:
            dfm["ESTADO_operacion"] = (
                dfm["ESTADO_operacion"]
                .astype(str)
                .replace({"Detenido": "Detenida", "detenido": "Detenida", "detenida": "Detenida"})
            )

        if "TIPO_asfalto" not in dfm.columns:
            es_plasto = dfm.get("es_plastomerico", pd.Series(0, index=dfm.index)).astype(int)
            dfm["TIPO_asfalto"] = np.where(es_plasto == 1, "Plastomerico", "Convencional")

        # Asegurar que estén presentes las 11 variables que usa el Modelo 3
        for col in VARIABLES_11_MODELO3:
            if col not in dfm.columns:
                dfm[col] = 0.0

        # Consolidar ráfagas sub-minuto a resolución de 1 minuto para no inflar litros ni minutos
        dfm["_minuto"] = dfm["timestamp"].dt.floor("min")
        if dfm["_minuto"].duplicated().any():
            agg_dict = {col: "mean" for col in VARIABLES_11_MODELO3}
            agg_dict["ESTADO_operacion"] = "last"
            agg_dict["TIPO_asfalto"] = "last"
            if "es_plastomerico" in dfm.columns:
                agg_dict["es_plastomerico"] = "max"
            if "en_limpieza" in dfm.columns:
                agg_dict["en_limpieza"] = "max"
            dfm = dfm.sort_values("timestamp").groupby("_minuto", as_index=False).agg(agg_dict)
            dfm = dfm.rename(columns={"_minuto": "timestamp"})
        else:
            dfm = dfm.drop(columns=["_minuto"]).sort_values("timestamp").reset_index(drop=True)

        modo = dfm["ESTADO_operacion"].astype(str) + "|" + dfm["TIPO_asfalto"].astype(str)
        ref_alineada = self.referencias_normal.reindex(modo)
        # Fallback a Produccion|Convencional si aparece una combinación no vista
        if ref_alineada.isna().any().any() and "Produccion|Convencional" in self.referencias_normal.index:
            ref_alineada = ref_alineada.fillna(self.referencias_normal.loc["Produccion|Convencional"])
        ref_alineada = ref_alineada.fillna(0.0)

        # Desviaciones de los 10 sensores respecto a su valor normal en el mismo modo (Estado x Tipo Asfalto)
        res = (dfm[self.sensores_10].astype("float32") - ref_alineada[self.sensores_10].values).astype("float32")
        activo = dfm["ESTADO_operacion"].isin(ESTADOS_ACTIVOS).values
        prod = (dfm["ESTADO_operacion"] == "Produccion").values
        plasto = (dfm["TIPO_asfalto"] == "Plastomerico").values | (dfm.get("es_plastomerico", 0) == 1)

        res.loc[~activo, self.sensores_10] = np.nan
        res.loc[~prod, self.solo_produccion] = np.nan
        res.loc[~(prod & plasto), "PRE_intercambiador_bar"] = np.nan
        res.columns = [f"dev_{c}" for c in self.sensores_10]

        hora = dfm["timestamp"].dt.floor("h")
        H = res.groupby(hora).mean()
        H["dev_VOLT_min"] = res["dev_VOLT_son_betum_in"].groupby(hora).min()
        H["picos_TEM"] = (res["dev_TEM_son_betum_in"] < -5).groupby(hora).sum()
        # 11ª variable directa: EST_niv_betum_dep -> EST_radar
        est_radar_serie = dfm["EST_niv_betum_dep"].astype("float32").where(activo, np.nan)
        H["EST_radar"] = est_radar_serie.groupby(hora).mean().values
        H["min_produccion"] = pd.Series(prod, index=dfm.index).groupby(hora).sum().values
        H["min_plastomerico"] = pd.Series(prod & plasto, index=dfm.index).groupby(hora).sum().values
        H["litros"] = pd.Series(dfm["CAU_bomba_lpm"].values * prod, index=dfm.index).groupby(hora).sum().values

        return H.sort_index()

    def _calcular_contadores_desgaste(self, H: pd.DataFrame, t_pred: pd.Timestamp, bitacora: dict | None = None) -> dict:
        """Calcula horas y desgaste acumulado por equipo desde la última intervención."""
        bitacora = bitacora or {}
        mapeo_claves_s3 = {
            "rodamientos": "ultima_mantencion_cojinetes",
            "filtro": "ultima_mantencion_filtro",
            "radar": "ultima_mantencion_radar",
            "caldera": "ultima_mantencion_caldera",
            "intercambiador": "ultima_mantencion_intercambiador",
            "caudalimetro": "ultima_mantencion_caudalimetro",
            "pt100": "ultima_mantencion_pt100",
        }
        t_inicio_ventana = H.index.min() if len(H) else (t_pred - pd.Timedelta(hours=168))

        contadores = {}
        for eq in self.intervenciones:
            fecha_str = bitacora.get(eq) or bitacora.get(f"ultima_mantencion_{eq}") or bitacora.get(mapeo_claves_s3.get(eq, ""))
            if fecha_str:
                try:
                    t_ult = pd.to_datetime(fecha_str, utc=True).tz_localize(None)
                except Exception:
                    t_ult = t_inicio_ventana
            else:
                t_ult = t_inicio_ventana

            H_desde = H[H.index >= t_ult]
            horas_trans = max(float((t_pred - t_ult) / pd.Timedelta(hours=1)), 1.0)
            contadores[eq] = {
                "ultima": t_ult,
                "horas": horas_trans,
                "litros": float(H_desde["litros"].sum()) if len(H_desde) else 0.0,
                "min_plasto": float(H_desde["min_plastomerico"].sum()) if len(H_desde) else 0.0,
                "min_prod": float(H_desde["min_produccion"].sum()) if len(H_desde) else 0.0,
            }
        return contadores

    def refactorizar_31_a_80_features(
        self,
        df_ventana_31: pd.DataFrame,
        bitacora: dict | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, dict]:
        """
        Paso obligatorio antes de ejecutar las predicciones del Modelo 3:
        Recibe el histórico/ventana de las 31 variables de entrada, las reduce a las 11
        variables base de degradación y construye exactamente las 80 variables tabulares:
          - 65 variables de tendencia (13 series base x 5 estadísticos: m24, m72, m168, d72, d168)
          - 10 variables de desgaste desde la última mantención (7 horas_desde_<eq> + 3 acumuladores físicos)
          - 1 variable de carga reciente (litros_24h)
          - 4 variables de calendario (estacion_sin, estacion_cos, dia_semana, hora)
        Total = 80 variables en el orden exacto de self.features_80.
        """
        H = self._resumen_horario_11_variables(df_ventana_31)
        t_pred = (H.index.max() if len(H) else pd.Timestamp.utcnow().tz_localize(None)).floor("h") + pd.Timedelta(hours=1)

        base_cols = [c for c in H.columns if c not in ("min_produccion", "min_plastomerico", "litros")]
        H_clean = H.copy()
        H_clean[base_cols] = H_clean[base_cols].ffill().fillna(0.0)

        tab: dict[str, float] = {}
        # 1) 13 columnas base x 5 métricas móviles = 65 features
        for c in base_cols:
            m24 = H_clean[c].rolling(24, min_periods=1).mean()
            tab[f"{c}_m24"] = float(m24.iloc[-1])
            tab[f"{c}_m72"] = float(H_clean[c].rolling(72, min_periods=1).mean().iloc[-1])
            tab[f"{c}_m168"] = float(H_clean[c].rolling(168, min_periods=1).mean().iloc[-1])
            tab[f"{c}_d72"] = float(m24.iloc[-1] - m24.iloc[-73]) if len(m24) > 72 else 0.0
            tab[f"{c}_d168"] = float(m24.iloc[-1] - m24.iloc[-169]) if len(m24) > 168 else 0.0

        # 2) 10 features de desgaste desde última intervención + 1 de caudal 24h
        contadores = self._calcular_contadores_desgaste(H_clean, t_pred, bitacora)
        for eq, info_eq in contadores.items():
            tab[f"horas_desde_{eq}"] = float(info_eq["horas"])

        tab["litros_desde_filtro"] = float(contadores["filtro"]["litros"] / 1000.0)
        tab["min_plasto_desde_intercambiador"] = float(contadores["intercambiador"]["min_plasto"])
        tab["horas_marcha_desde_rodamientos"] = float(contadores["rodamientos"]["min_prod"] / 60.0)
        tab["litros_24h"] = float(H_clean["litros"].iloc[-24:].sum() / 1000.0)

        # 3) 4 features de contexto de calendario
        doy = t_pred.dayofyear
        tab["estacion_sin"] = float(np.sin(2.0 * np.pi * doy / 365.0))
        tab["estacion_cos"] = float(np.cos(2.0 * np.pi * doy / 365.0))
        tab["dia_semana"] = float(t_pred.dayofweek)
        tab["hora"] = float(t_pred.hour)

        fila_ordenada = {f: float(np.nan_to_num(tab.get(f, 0.0))) for f in self.features_80}
        X_80 = pd.DataFrame([fila_ordenada], columns=self.features_80).astype("float32")
        # Retornamos H sin imputar para que _estimar_dias_tendencia ignore horas detenidas/no aplicables
        return X_80, H, t_pred, contadores

    def _estimar_dias_tendencia(self, H: pd.DataFrame, falla: str, t_pred: pd.Timestamp) -> tuple[float | None, float | None]:
        """Ajusta regresión lineal sobre los últimos días para fallas raras (Modelo 3 Tendencia)."""
        if falla not in self.reglas_tendencia or falla not in COLUMNA_TENDENCIA_POR_FALLA:
            return None, None
        lim = self.reglas_tendencia[falla]
        col = COLUMNA_TENDENCIA_POR_FALLA[falla]
        if col not in H.columns or len(H) == 0:
            return None, None

        agg = "median" if falla == "Falla_Electrica_PT100_Betun" else "mean"
        s = H[col].resample("D").agg(agg).dropna()
        s_prev = s[s.index < t_pred.floor("D")].iloc[-7:]
        if len(s_prev) < 3:
            # Cold Start: requerir al menos 6 horas válidas y 24h de amplitud temporal para proyectar pendiente
            s_horas = H[col].dropna().iloc[-168:]
            if len(s_horas) == 0:
                return None, None
            span_horas = (s_horas.index[-1] - s_horas.index[0]) / pd.Timedelta(hours=1)
            if len(s_horas) < 6 or span_horas < 24.0:
                actual = float(s_horas.iloc[-1])
                signo = float(lim.get("signo", 1.0))
                limite = float(lim.get("limite", 1.0))
                if signo * (actual - limite) >= 0:
                    return 0.0, actual
                return None, actual
            x = ((s_horas.index - s_horas.index[0]) / pd.Timedelta(days=1)).values.astype(float)
            if np.allclose(x, x[0]):
                return None, float(s_horas.iloc[-1])
            pend, inter = np.polyfit(x, s_horas.values, 1)
            actual = float(pend * x[-1] + inter)
        else:
            x = (s_prev.index - s_prev.index[0]).days.values.astype(float)
            pend, inter = np.polyfit(x, s_prev.values, 1)
            actual = float(pend * x[-1] + inter)

        signo = float(lim.get("signo", 1.0))
        limite = float(lim.get("limite", 1.0))
        if signo * (actual - limite) >= 0:
            return 0.0, actual
        if signo * pend > 1e-6:
            return float((limite - actual) / pend), actual
        return float("inf"), actual

    def ejecutar_predictivo_desde_31(
        self,
        df_ventana_31: pd.DataFrame,
        bitacora: dict | None = None,
    ) -> dict:
        """
        Ejecuta el Modelo 3 recibiendo las 31 variables de entrada (en ventana temporal),
        refactorizándolas primero a las 11 variables base y luego a las 80 features tabulares.
        """
        X_80, H_raw, t_pred, _ = self.refactorizar_31_a_80_features(df_ventana_31, bitacora)
        return self._evaluar_modelos_80(X_80, H_raw, t_pred)

    def ejecutar_predictivo(
        self,
        payload_entrada: dict | pd.DataFrame,
        bitacora: dict | None = None,
    ) -> dict:
        """
        Punto de entrada flexible para el Modelo 3:
        - Si recibe un DataFrame o dict con las 31 variables de entrada, ejecuta la
          refactorización 31 -> 11 -> 80 antes de predecir.
        - Si ya recibe las 80 variables precalculadas, las alinea y evalúa directamente.
        """
        if isinstance(payload_entrada, pd.DataFrame):
            return self.ejecutar_predictivo_desde_31(payload_entrada, bitacora)

        if all(col in payload_entrada for col in self.features_80):
            X_80 = pd.DataFrame([payload_entrada])[self.features_80].astype("float32")
            H_vacio = pd.DataFrame()
            t_pred = pd.Timestamp.utcnow().tz_localize(None)
            return self._evaluar_modelos_80(X_80, H_vacio, t_pred)

        # Caso general: viene un registro con las 31 variables de entrada
        registro_31 = self.Normalizar_Entrada_31(payload_entrada)
        df_31 = pd.DataFrame([registro_31])
        return self.ejecutar_predictivo_desde_31(df_31, bitacora)

    def _evaluar_modelos_80(
        self,
        X_80: pd.DataFrame,
        H_raw: pd.DataFrame,
        t_pred: pd.Timestamp,
    ) -> dict:
        alertas = []
        pronosticos = {}

        # 1. 9 Modelos LightGBM (3 fallas frecuentes x 3 horizontes: '24 h', '5 días', '15 días')
        for falla in self.fallas_ml:
            pronosticos[falla] = {"metodo": self.familia_pred, "horizontes": {}}
            for hz in self.horizontes:
                modelo = self.modelos_ml[(falla, hz)]
                prob = float(modelo.predict_proba(X_80)[0, 1])
                umbral = float(self.umbrales_ml[(falla, hz)])
                activa = prob >= umbral
                pronosticos[falla]["horizontes"][hz] = {
                    "probabilidad": round(prob, 4),
                    "umbral": round(umbral, 4),
                    "alerta": bool(activa),
                }
                if activa:
                    alertas.append({
                        "metodo": "LightGBM_MultiHorizonte",
                        "falla": falla,
                        "horizonte": hz,
                        "probabilidad": round(prob, 4),
                        "umbral": round(umbral, 4),
                        "accion_recomendada": self.acciones.get(falla, ""),
                    })

        # 2. 4 Fallas raras por proyección de tendencia lineal
        for falla in self.fallas_tendencia:
            dias_est, val_actual = self._estimar_dias_tendencia(H_raw, falla, t_pred)
            pronosticos[falla] = {
                "metodo": "Tendencia",
                "dias_estimados": round(dias_est, 2) if dias_est is not None and np.isfinite(dias_est) else None,
                "indicador_actual": round(val_actual, 4) if val_actual is not None else None,
                "horizontes": {},
            }
            for hz, horas_hz in self.horizontes.items():
                activa = dias_est is not None and dias_est <= (horas_hz / 24.0)
                prob_equiv = 1.0 if activa else 0.0
                pronosticos[falla]["horizontes"][hz] = {
                    "alerta": bool(activa),
                    "probabilidad": prob_equiv,
                }
                if activa:
                    alertas.append({
                        "metodo": "Regla_Tendencia",
                        "falla": falla,
                        "horizonte": hz,
                        "probabilidad": prob_equiv,
                        "dias_estimados": round(dias_est, 2) if dias_est is not None and np.isfinite(dias_est) else None,
                        "valor_actual": round(val_actual, 4) if val_actual is not None else None,
                        "accion_recomendada": self.acciones.get(falla, ""),
                    })

        return {
            "variables_entrada_31": len(self.features_31),
            "variables_intermedias_11": len(VARIABLES_11_MODELO3),
            "variables_tabulares_80": X_80.shape[1],
            "total_alertas": len(alertas),
            "alertas_preventivas": alertas,
            "pronosticos": pronosticos,
        }
