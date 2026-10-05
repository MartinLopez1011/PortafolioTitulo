"""
Química Latinoamericana: monitor y mantenimiento predictivo del molino coloidal MC-01.

Integra:
  - Reglas fijas para fallas de instrumento y límites de proceso.
  - Identificación de fallas (modelo jerárquico exportado del notebook, LightGBM).
  - Autoencoder para anomalías y degradación (fallas raras o desconocidas).
  - Predicción de fallas a 24 h, 5 días y 15 días (LightGBM + tendencia).

Ejecutar:  uvicorn app:app --reload   y abrir http://127.0.0.1:8000
"""
import csv
import io
import threading
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config as cfg
import escenarios as esc
import modelos
import registro
from fuentes import Reproductor
from predictivo import Predictor

app = FastAPI(title=f"{cfg.EMPRESA}: {cfg.EQUIPO}")
app.mount("/static", StaticFiles(directory=cfg.BASE / "static"), name="static")

rep = Reproductor()
pred = Predictor()
alarmas = registro.GestorAlarmas()
kpis = registro.Indicadores()
_lock = threading.Lock()
estado = {"pendiente": [], "ultimo": None}
bit_csv = (pd.read_csv(cfg.RUTA_BITACORA, parse_dates=["timestamp"]) if cfg.RUTA_BITACORA.exists()
           else pd.DataFrame(columns=["timestamp", "equipo", "tipo", "descripcion"]))
ESCENARIO_EQUIPO = {"Caldera perdiendo potencia": "caldera", "Filtro obstruyéndose": "filtro", "Radar ensuciándose": "radar",
                    "Humedad en caudalímetro": "caudalimetro", "Cortocircuito caudalímetro": "caudalimetro",
                    "Borneras Pt100 corroídas": "pt100", "Pt100 sin alimentación": "pt100",
                    "Intercambiador ensuciándose": "intercambiador", "Rodamientos desgastándose": "rodamientos"}

# Bandas de operación normal por modo (estado|tipo), con datos normales del primer semestre
_ref = rep.df[(rep.df["LABEL_Estado_Planta"] == "Normal") & (rep.df["timestamp"] < "2026-07-01")]
_modo = _ref["ESTADO_operacion"] + "|" + _ref["TIPO_asfalto"]
SENS_NUM = [s for s in cfg.SENSORES if s in rep.df.columns]
BANDAS = {m: {s: [float(g[s].quantile(0.005)), float(g[s].quantile(0.995))] for s in SENS_NUM}
          for m, g in _ref.groupby(_modo)}


def bitacora_hasta(t):
    usr = pd.DataFrame(registro.intervenciones_usuario())
    if len(usr):
        usr = usr.rename(columns={"tiempo": "timestamp"})[["timestamp", "equipo", "tipo", "descripcion"]]
        usr["timestamp"] = pd.to_datetime(usr["timestamp"])
    b = pd.concat([bit_csv, usr]) if len(usr) else bit_csv.copy()
    return b[b["timestamp"] <= t].sort_values("timestamp")


def ir_a(indice):
    rep.forzar(None)
    rep.ir_a(indice)
    rep.activar(None)
    t0 = rep.tiempo
    alarmas.reiniciar(t0)
    kpis.reiniciar()
    estado["pendiente"] = []
    pred.inicializar(rep.historia(), bitacora_hasta(t0), rep.df["timestamp"].iloc[0])
    # índice de salud: se precalculan los 45 días previos con el autoencoder
    registro.limpiar_lecturas_desde(t0 - pd.Timedelta(days=60))
    if modelos.AE_OK:
        h = rep.df[(rep.df["timestamp"] >= t0 - pd.Timedelta(days=45)) & (rep.df["timestamp"] < t0)]
        h = h[h["ESTADO_operacion"].isin(cfg.ESTADOS_MARCHA)]
        if len(h):
            d = modelos._contexto(h)
            Xa = modelos._ae_cfg["scaler"].transform(d[modelos._ae_cfg["features"]]).astype("float32")
            err = ((Xa - modelos._ae(Xa, training=False).numpy()) ** 2).mean(axis=1)
            registro.guardar_lecturas(list(zip(h["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S"), h["LABEL_Estado_Planta"], err.astype(float))))


ir_a(int(np.searchsorted(rep.df["timestamp"].values, np.datetime64("2026-09-01T07:00"))))


# ------------------------------------------------------------------ páginas e información
@app.get("/")
def inicio():
    return FileResponse(cfg.BASE / "static" / "index.html")


@app.get("/api/info")
def info():
    return {"empresa": cfg.EMPRESA, "equipo": cfg.EQUIPO, "planta": cfg.PLANTA,
            "modelos": {**modelos.estado_modelos(), "prediccion": pred.pq["familia"] if pred.ok else None},
            "sensores": [{"id": k, "nombre": v[0], "unidad": v[1], "equipo": v[2]} for k, v in cfg.SENSORES.items()],
            "fallas": cfg.FALLAS, "corto": cfg.CORTO, "episodios": rep.episodios,
            "equipos": {k: v[0] for k, v in cfg.INTERVENCIONES_UI.items()},
            "persistencia": [cfg.PERSISTENCIA_ACTIVAR, cfg.PERSISTENCIA_VENTANA]}


# ------------------------------------------------------------------ ciclo de simulación
@app.post("/api/paso")
def paso(n: int = 1):
    n = max(1, min(n, 480))
    with _lock:
        bloque = rep.siguiente(n)
        evs = modelos.evaluar_lote(bloque)
        filas_db = []
        for (_, fila), ev in zip(bloque.iterrows(), evs):
            marcha = fila["ESTADO_operacion"] in cfg.ESTADOS_MARCHA
            lect = {s: float(fila[s]) for s in SENS_NUM}
            alarmas.procesar(fila["timestamp"], "simulacion" if rep.escenario else "historico", ev, lect, marcha)
            kpis.actualizar(fila, ev["estado"], marcha)
            if ev["autoencoder"]:
                filas_db.append((fila["timestamp"].isoformat(), ev["estado"], ev["autoencoder"]["error"]))
        registro.guardar_lecturas(filas_db)

        # predicción: se actualiza al cerrar cada hora
        estado["pendiente"].append(bloque)
        pend = pd.concat(estado["pendiente"])
        hora_actual = pend["timestamp"].iloc[-1].floor("h")
        for h, g in pend[pend["timestamp"] < hora_actual].groupby(pend["timestamp"].dt.floor("h")):
            pred.agregar_hora(g)
        estado["pendiente"] = [pend[pend["timestamp"] >= hora_actual]]

        ult = bloque.iloc[-1]
        modo = f"{ult['ESTADO_operacion']}|{ult['TIPO_asfalto']}"
        banda = BANDAS.get(modo, {})
        cols = SENS_NUM
        estado["ultimo"] = {
            "tiempo": ult["timestamp"].isoformat(timespec="minutes"),
            "operacion": ult["ESTADO_operacion"], "tipo": ult["TIPO_asfalto"],
            "lecturas": {s: float(ult[s]) for s in cols}, "banda": banda,
            "etiqueta_real": ult["LABEL_Estado_Planta"],
            "evaluacion": evs[-1],
            "alarmas": alarmas.listar_activas(),
            "kpis": kpis.resumen(ult),
            "prediccion": pred.ultimo if pred.ok else None,
            "fuente": rep.info(),
            "serie": {"tiempo": bloque["timestamp"].dt.strftime("%Y-%m-%dT%H:%M").tolist(),
                      "estado": [e["estado"] for e in evs],
                      "ae": [e["autoencoder"]["error"] if e["autoencoder"] else None for e in evs],
                      **{s: bloque[s].round(3).tolist() for s in cols}},
        }
        return estado["ultimo"]


class IrA(BaseModel):
    indice: Optional[int] = None
    fecha: Optional[str] = None


@app.post("/api/ir")
def ir(body: IrA):
    with _lock:
        if body.fecha:
            i = int(np.searchsorted(rep.df["timestamp"].values, np.datetime64(pd.Timestamp(body.fecha))))
        else:
            i = body.indice or 0
        ir_a(i)
    return rep.info()


class Funcionamiento(BaseModel):
    modo: Optional[str] = None      # None = calendario real del año 2026


@app.post("/api/funcionamiento")
def funcionamiento(body: Funcionamiento):
    with _lock:
        if body.modo:
            try:
                rep.forzar(body.modo)
            except ValueError:
                raise HTTPException(422, "Modo de funcionamiento desconocido.")
            alarmas.reiniciar(rep.tiempo)
        else:
            ir_a(rep.pos)          # vuelve al calendario real donde quedó la reproducción
    return rep.info()


class ActivarEscenario(BaseModel):
    nombre: Optional[str] = None
    escenario: Optional[esc.Escenario] = None


@app.post("/api/escenario")
def activar_escenario(body: ActivarEscenario):
    if body.escenario:
        e = body.escenario.model_dump()
    elif body.nombre:
        e = next((x for x in esc.todos() if x["nombre"] == body.nombre), None)
        if e is None:
            raise HTTPException(404, f'No existe el escenario "{body.nombre}".')
    else:
        e = None
    with _lock:
        rep.activar(e)
    return rep.info()


@app.get("/api/escenarios")
def listar_escenarios():
    return esc.todos()


@app.post("/api/escenarios")
def guardar_escenario(escenario: esc.Escenario):
    nombre = escenario.nombre.strip()
    if nombre.lower() in esc.nombres_reservados():
        raise HTTPException(409, f'"{nombre}" es un escenario del sistema. Elige otro nombre.')
    desconocidos = sorted({e.sensor for e in escenario.efectos} - set(SENS_NUM))
    if desconocidos:
        raise HTTPException(422, f"Sensores desconocidos: {', '.join(desconocidos)}")
    escenario.nombre = nombre
    esc.guardar_personalizado(escenario)
    return {"guardado": nombre}


@app.delete("/api/escenarios/{nombre}")
def eliminar_escenario(nombre: str):
    if not esc.eliminar_personalizado(nombre):
        raise HTTPException(404, f'No existe una falla personalizada llamada "{nombre}".')
    return {"eliminado": nombre}


# ------------------------------------------------------------------ mantenimiento
class Intervencion(BaseModel):
    equipo: str
    tipo: Literal["Preventiva", "Correctiva"] = "Preventiva"
    descripcion: str = Field(default="", max_length=300)
    usuario: str = Field(default="Operador", max_length=60)


@app.post("/api/mantenimiento")
def registrar(body: Intervencion):
    if body.equipo not in cfg.INTERVENCIONES_UI:
        raise HTTPException(422, "Equipo desconocido.")
    nombre, desc = cfg.INTERVENCIONES_UI[body.equipo]
    with _lock:
        t = rep.tiempo
        registro.registrar_intervencion(t, nombre, body.equipo, body.tipo, body.descripcion or desc, body.usuario or "Operador")
        pred.registrar_intervencion(body.equipo, t)
        resuelto = None
        if rep.escenario and ESCENARIO_EQUIPO.get(rep.escenario["nombre"]) == body.equipo:
            resuelto = rep.escenario["nombre"]
            rep.activar(None)                     # la intervención corrige la falla simulada
        if pred.ok:
            pred.ultimo = pred._predecir(t.floor("h") + pd.Timedelta(hours=1))
    return {"ok": True, "tiempo": t.isoformat(timespec="minutes"), "escenario_resuelto": resuelto}


@app.get("/api/mantenimiento")
def mantenimiento():
    t = rep.tiempo
    b = bitacora_hasta(t)
    filas = []
    for clave, (nombre, _) in cfg.INTERVENCIONES_UI.items():
        txt, txt_mensual = pred.pq["intervenciones"][clave] if pred.ok else (clave, clave)
        e = b[b["equipo"].str.lower().str.contains(txt) |
              ((b["tipo"] != "Correctiva") & b["descripcion"].str.lower().str.contains(txt_mensual))]
        corr = e[e["tipo"] == "Correctiva"]["timestamp"]
        mtbf = corr.diff().dt.total_seconds().div(86400).mean() if len(corr) > 1 else None
        c = pred.contadores.get(clave) if pred.ok else None
        filas.append({"clave": clave, "equipo": nombre, "correctivas": int(len(corr)),
                      "preventivas": int((e["tipo"] != "Correctiva").sum()),
                      "mtbf_dias": None if mtbf is None or np.isnan(mtbf) else float(mtbf),
                      "ultima_intervencion": c["ultima"].isoformat(timespec="minutes") if c else None,
                      "horas_desde": (t - c["ultima"]) / pd.Timedelta(hours=1) if c else None})
    total = len(b)
    prev = int((b["tipo"] != "Correctiva").sum())
    return {"tiempo": t.isoformat(timespec="minutes"), "equipos": filas,
            "pct_planificado": 100 * prev / total if total else None, "total": total,
            "bitacora": [{"tiempo": r.timestamp.isoformat(timespec="minutes"), "equipo": r.equipo, "tipo": r.tipo,
                          "descripcion": r.descripcion} for r in b.iloc[::-1].head(60).itertuples()]}


# ------------------------------------------------------------------ alarmas, salud, etiquetas
@app.get("/api/alarmas")
def listar_alarmas():
    return {"activas": alarmas.listar_activas(), "historial": registro.historial_alarmas()}


class Reconocimiento(BaseModel):
    usuario: str = Field(default="Operador", max_length=60)


@app.post("/api/alarmas/{id_}/reconocer")
def reconocer(id_: int, body: Reconocimiento):
    registro.reconocer(id_, body.usuario or "Operador", rep.tiempo.isoformat(timespec="minutes"))
    return {"ok": True}


class Retro(BaseModel):
    valor: Literal["correcto", "incorrecto", "otra"]
    texto: str = Field(default="", max_length=300)


@app.post("/api/alarmas/{id_}/retroalimentacion")
def retroalimentar(id_: int, body: Retro):
    registro.retroalimentar(id_, body.valor, body.texto, rep.tiempo.isoformat(timespec="minutes"))
    return {"ok": True}


@app.get("/api/salud")
def salud():
    return {"umbral": modelos.UMBRAL_AE, "dias": registro.salud_diaria()}


@app.get("/api/etiquetas")
def etiquetas():
    return registro.etiquetas()


@app.get("/api/etiquetas.csv")
def etiquetas_csv():
    filas = registro.etiquetas()
    buf = io.StringIO()
    if filas:
        w = csv.DictWriter(buf, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=etiquetas_operador.csv"})
