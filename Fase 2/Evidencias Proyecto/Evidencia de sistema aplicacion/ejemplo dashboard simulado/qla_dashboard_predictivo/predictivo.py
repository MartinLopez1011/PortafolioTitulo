"""
Predicción de fallas a 24 h, 5 días y 15 días.

Reproduce exactamente la construcción de variables del notebook de predicción:
desviaciones respecto de lo normal por modo de operación, resumen por hora,
tendencias (24 h, 3 y 7 días), desgaste acumulado desde la última intervención y calendario.
"""
import joblib
import numpy as np
import pandas as pd

import config as cfg

PRED_OK = cfg.RUTA_PREDICTIVO.exists()
HORAS_BUFFER = 400


def _desviaciones(dfm, pq):
    modo = dfm["ESTADO_operacion"] + "|" + dfm["TIPO_asfalto"]
    ref = pq["referencias_normal"]
    res = (dfm[pq["sensores"]] - ref.reindex(modo).values).astype("float32")
    prod = (dfm["ESTADO_operacion"] == "Produccion").values
    res.loc[~prod, pq["solo_produccion"]] = np.nan
    res.loc[~(prod & (dfm["TIPO_asfalto"] == "Plastomerico").values), "PRE_intercambiador_bar"] = np.nan
    res.columns = [f"dev_{c}" for c in pq["sensores"]]
    return res, prod


def horas_base(dfm, pq):
    """Resumen por hora (sin rellenar) de un bloque de minutos."""
    res, prod = _desviaciones(dfm, pq)
    hora = dfm["timestamp"].dt.floor("h").values
    H = res.groupby(hora).mean()
    H["dev_VOLT_min"] = res["dev_VOLT_son_betum_in"].groupby(hora).min()
    H["picos_TEM"] = (res["dev_TEM_son_betum_in"] < -5).groupby(hora).sum()
    H["EST_radar"] = dfm["EST_niv_betum_dep"].groupby(hora).mean().values
    H["min_produccion"] = pd.Series(prod).groupby(hora).sum().values
    H["min_plastomerico"] = pd.Series(prod & (dfm["TIPO_asfalto"] == "Plastomerico").values).groupby(hora).sum().values
    H["litros"] = pd.Series(dfm["CAU_bomba_lpm"].values * prod).groupby(hora).sum().values
    return H


class Predictor:
    def __init__(self):
        self.ok = PRED_OK
        if not self.ok:
            return
        self.pq = joblib.load(cfg.RUTA_PREDICTIVO)
        if self.pq["familia"] not in ("LightGBM", "Random Forest"):
            raise RuntimeError("El dashboard soporta modelos predictivos LightGBM o Random Forest.")
        self.H = None
        self.ultimo = None

    # ------------------------------------------------------------------ intervenciones
    def _fechas_intervencion(self, bit, eq):
        txt_equipo, txt_mensual = self.pq["intervenciones"][eq]
        corr = bit.loc[(bit["tipo"] == "Correctiva") & bit["equipo"].str.lower().str.contains(txt_equipo), "timestamp"]
        otras = bit.loc[(bit["tipo"] != "Correctiva") & (
            bit["descripcion"].str.lower().str.contains(txt_mensual) | bit["equipo"].str.lower().str.contains(txt_equipo)), "timestamp"]
        return pd.concat([corr, otras]).sort_values()

    def inicializar(self, df_hist, bit, inicio_datos):
        """Prepara el buffer horario y los contadores de desgaste con los datos previos a la simulación."""
        if not self.ok:
            return
        t0 = df_hist["timestamp"].max()
        ventana = df_hist[df_hist["timestamp"] > t0 - pd.Timedelta(hours=HORAS_BUFFER)]
        self.H = horas_base(ventana, self.pq)
        self.contadores = {}
        prod = (df_hist["ESTADO_operacion"] == "Produccion").values
        litros = df_hist["CAU_bomba_lpm"].values * prod
        plasto = prod & (df_hist["TIPO_asfalto"] == "Plastomerico").values
        ts = df_hist["timestamp"].values
        for eq in self.pq["intervenciones"]:
            f = self._fechas_intervencion(bit[bit["timestamp"] <= t0], eq)
            ultima = f.iloc[-1] if len(f) else inicio_datos
            m = ts >= np.datetime64(ultima)
            self.contadores[eq] = {"ultima": pd.Timestamp(ultima), "litros": float(litros[m].sum()),
                                   "min_plasto": float(plasto[m].sum()), "min_prod": float(prod[m].sum())}
        self.ultimo = self._predecir(t0.floor("h") + pd.Timedelta(hours=1))

    def registrar_intervencion(self, eq, t):
        if self.ok and eq in self.contadores:
            self.contadores[eq] = {"ultima": pd.Timestamp(t), "litros": 0.0, "min_plasto": 0.0, "min_prod": 0.0}

    def agregar_hora(self, dfm_hora):
        """Recibe los minutos de una hora completa y actualiza la predicción."""
        if not self.ok:
            return None
        h = horas_base(dfm_hora, self.pq)
        self.H = pd.concat([self.H, h])
        self.H = self.H[~self.H.index.duplicated(keep="last")].iloc[-HORAS_BUFFER:]
        for c in self.contadores.values():
            c["litros"] += float(h["litros"].sum())
            c["min_plasto"] += float(h["min_plastomerico"].sum())
            c["min_prod"] += float(h["min_produccion"].sum())
        self.ultimo = self._predecir(h.index.max() + pd.Timedelta(hours=1))
        return self.ultimo

    # ------------------------------------------------------------------ variables y predicción
    def _variables(self, t_pred):
        H = self.H.copy()
        base = [c for c in H.columns if c not in ("min_produccion", "min_plastomerico", "litros")]
        H[base] = H[base].ffill().fillna(0)
        tab = {}
        for c in base:
            m24 = H[c].rolling(24, min_periods=1).mean()
            tab[f"{c}_m24"] = m24.iloc[-1]
            tab[f"{c}_m72"] = H[c].rolling(72, min_periods=1).mean().iloc[-1]
            tab[f"{c}_m168"] = H[c].rolling(168, min_periods=1).mean().iloc[-1]
            tab[f"{c}_d72"] = m24.iloc[-1] - m24.iloc[-73] if len(m24) > 72 else 0.0
            tab[f"{c}_d168"] = m24.iloc[-1] - m24.iloc[-169] if len(m24) > 168 else 0.0
        for eq, c in self.contadores.items():
            tab[f"horas_desde_{eq}"] = (t_pred - c["ultima"]) / pd.Timedelta(hours=1)
        tab["litros_desde_filtro"] = self.contadores["filtro"]["litros"] / 1000
        tab["min_plasto_desde_intercambiador"] = self.contadores["intercambiador"]["min_plasto"]
        tab["horas_marcha_desde_rodamientos"] = self.contadores["rodamientos"]["min_prod"] / 60
        tab["litros_24h"] = H["litros"].iloc[-24:].sum() / 1000
        doy = t_pred.dayofyear
        tab["estacion_sin"], tab["estacion_cos"] = np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)
        tab["dia_semana"], tab["hora"] = t_pred.dayofweek, t_pred.hour
        return np.array([[float(np.nan_to_num(tab.get(f, 0.0))) for f in self.pq["features_tabulares"]]], dtype="float32")

    def _tendencia(self, falla, t_pred):
        lim = self.pq["tendencia"][falla]
        col = {"Cortocircuito_Transmisor_Caudal_Sol": "dev_AMP_cau_solucion_in", "Falla_Electrica_PT100_Betun": "dev_VOLT_son_betum_in",
               "Ensuciamiento_Intercambiador": "dev_PRE_intercambiador_bar", "Desgaste_Rodamientos_Molino": "dev_VIB_vel_motor_molino",
               "Filtro_Obstruido": "dev_PRE_dif_filtro_bar"}[falla]
        agg = "median" if falla == "Falla_Electrica_PT100_Betun" else "mean"
        s = self.H[col].resample("D").agg(agg).dropna()
        s = s[s.index < t_pred.floor("D")].iloc[-7:]
        if len(s) < 3:
            return None, None
        x = (s.index - s.index[0]).days.values.astype(float)
        pend, inter = np.polyfit(x, s.values, 1)
        actual = pend * x[-1] + inter
        if lim["signo"] * (actual - lim["limite"]) >= 0:
            return 0.0, float(actual)
        if lim["signo"] * pend > 1e-6:
            return float((lim["limite"] - actual) / pend), float(actual)
        return float("inf"), float(actual)

    def _predecir(self, t_pred):
        X = self._variables(t_pred)
        pq, filas = self.pq, []
        for f in pq["fallas_ml"]:
            fila = {"falla": f, "nombre": cfg.CORTO[f], "metodo": pq["familia"], "horizontes": {}}
            for hz in pq["horizontes"]:
                if pq["familia"] == "LightGBM":
                    p = float(pq["modelos"][f, hz].predict_proba(X)[0, 1])
                else:
                    p = float(pq["modelos"][hz].predict_proba(X)[pq["fallas_ml"].index(f)][0, 1])
                fila["horizontes"][hz] = {"prob": p, "umbral": pq["umbrales"][f, hz], "alerta": p >= pq["umbrales"][f, hz]}
            filas.append(fila)
        for f in pq["fallas_tendencia"]:
            dias, actual = self._tendencia(f, t_pred)
            fila = {"falla": f, "nombre": cfg.CORTO[f], "metodo": "Tendencia",
                    "dias": dias if dias is not None and np.isfinite(dias) else None, "indicador": actual, "horizontes": {}}
            for hz, h in pq["horizontes"].items():
                fila["horizontes"][hz] = {"alerta": dias is not None and dias <= h / 24}
            filas.append(fila)
        for fila in filas:
            eq = cfg.EQUIPO_DE_FALLA[fila["falla"]]
            fila["equipo"], fila["accion"] = eq, pq["acciones"][fila["falla"]]
            fila["horas_desde_intervencion"] = (t_pred - self.contadores[eq]["ultima"]) / pd.Timedelta(hours=1)
            fila["nivel"] = next((hz for hz in pq["horizontes"] if fila["horizontes"][hz]["alerta"]), None)
        return {"tiempo": t_pred.isoformat(timespec="minutes"), "horizontes": list(pq["horizontes"]), "filas": filas}
