"""Modelos de diagnóstico en tiempo real: identificación de fallas y autoencoder."""
import joblib
import numpy as np

import config as cfg

ID_OK = cfg.RUTA_IDENTIFICACION.exists()
AE_OK = cfg.RUTA_AE.exists() and cfg.RUTA_AE_CONFIG.exists()
_keras = None


def _cargar_keras(ruta):
    global _keras
    if _keras is None:
        from tensorflow import keras as k
        _keras = k
    return _keras.models.load_model(cfg.BASE / ruta if isinstance(ruta, str) else ruta)


if ID_OK:
    _id = joblib.load(cfg.RUTA_IDENTIFICACION)
    for etapa in ("modelo_etapa1", "modelo_etapa2"):
        if isinstance(_id[etapa], str):                    # la etapa es una MLP guardada como .keras
            _id[etapa] = _cargar_keras(_id[etapa])
    NOMBRE_ID = _id.get("sistema", "Identificación")
if AE_OK:
    _ae = _cargar_keras(cfg.RUTA_AE)
    _ae_cfg = joblib.load(cfg.RUTA_AE_CONFIG)
    UMBRAL_AE = float(_ae_cfg["umbral"])
else:
    UMBRAL_AE = None


def estado_modelos():
    return {"identificacion": NOMBRE_ID if ID_OK else None, "autoencoder": f"Autoencoder ({_ae_cfg['variante']})" if AE_OK else None,
            "umbral_ae": UMBRAL_AE}


def _predecir(modelo, X):
    if hasattr(modelo, "predict_proba") and not hasattr(modelo, "layers"):
        return modelo.predict(X)
    p = modelo.predict(X, verbose=0)
    return (p.ravel() >= 0.5).astype(int) if p.shape[1] == 1 else p.argmax(axis=1)


def _contexto(dfm):
    d = dfm.copy()
    d["es_plastomerico"] = (d["TIPO_asfalto"] == "Plastomerico").astype(int)
    d["en_limpieza"] = (d["ESTADO_operacion"] == "Limpieza").astype(int)
    return d


def evaluar_lote(dfm):
    """Evalúa un bloque de minutos. Devuelve una lista de diccionarios, uno por minuto."""
    n = len(dfm)
    marcha = dfm["ESTADO_operacion"].isin(cfg.ESTADOS_MARCHA).values
    salida = [{"estado": "Detenida", "origen": "Molino detenido: los modelos se aplican con el molino en marcha",
               "identificacion": None, "autoencoder": None} for _ in range(n)]
    if not marcha.any():
        return salida
    d = _contexto(dfm.loc[marcha])
    idx = np.where(marcha)[0]

    ident = [None] * len(d)
    if ID_OK:
        X = _id["scaler"].transform(d[_id["features"]]).astype("float32")
        anom = _predecir(_id["modelo_etapa1"], X)
        ident = np.array(["Normal"] * len(d), dtype=object)
        j = np.where(anom == 1)[0]
        if len(j):
            ident[j] = _id["label_encoder_fallas"].inverse_transform(_predecir(_id["modelo_etapa2"], X[j]))

    ae_res = [None] * len(d)
    if AE_OK:
        Xa = _ae_cfg["scaler"].transform(d[_ae_cfg["features"]]).astype("float32")
        err = (Xa - _ae(Xa, training=False).numpy()) ** 2
        media = err.mean(axis=1)
        top = np.argsort(err, axis=1)[:, ::-1][:, :3]
        tot = err.sum(axis=1) + 1e-9
        f = _ae_cfg["features"]
        ae_res = [{"error": float(media[k]), "anomalia": bool(media[k] > UMBRAL_AE),
                   "sensores": [{"id": f[i], "nombre": cfg.SENSORES.get(f[i], (f[i],))[0], "aporte": float(err[k, i] / tot[k])}
                                for i in top[k]]} for k in range(len(d))]

    for k, i in enumerate(idx):
        ide, ae = ident[k], ae_res[k]
        estado, origen = "Normal", "LightGBM y autoencoder ven operación normal"
        if ide is not None and ide != "Normal":
            estado, origen = ide, f"Identificado por {NOMBRE_ID}"
            if ae and ae["anomalia"]:
                origen += ", con anomalía confirmada por el autoencoder"
        elif ae and ae["anomalia"]:
            ids = {s["id"] for s in ae["sensores"][:2]}
            rara = next((fa for fa, firma in cfg.FIRMA_FALLAS_RARAS.items() if firma & ids), None)
            nombres = ", ".join(s["nombre"] for s in ae["sensores"])
            if rara:
                estado, origen = rara, f"Detectado por el autoencoder (falla rara que LightGBM casi no conoce). Revisar: {nombres}"
            else:
                estado, origen = "Anomalia_Desconocida", f"Aviso de degradación del autoencoder. Revisar: {nombres}"
        elif ide is None and ae is None:
            origen = "Sin modelos cargados"
        salida[i] = {"estado": estado, "origen": origen, "identificacion": None if ide is None else str(ide), "autoencoder": ae}
    return salida
