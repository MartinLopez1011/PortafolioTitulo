"""
Fuente de datos: reproduce el año de operación minuto a minuto y permite inyectar
escenarios de falla encima de los datos reales (simulación).

Para conectar la planta real, reemplazar `siguiente()` por una lectura del PLC
(OPC UA con asyncua o Modbus TCP con pymodbus) que entregue las mismas columnas.
"""
import numpy as np
import pandas as pd

import config as cfg

# Modos de funcionamiento que se pueden fijar para demostrar cómo opera la planta
MODOS = {
    "produccion_convencional": ("Produccion", "Convencional"),
    "produccion_plastomerico": ("Produccion", "Plastomerico"),
    "limpieza": ("Limpieza", "Convencional"),
    "preparacion": ("Preparacion", "Convencional"),
    "espera": ("Espera", "Convencional"),
    "detenida": ("Detenida", "Ninguno"),
}


class Reproductor:
    def __init__(self):
        if not cfg.RUTA_HISTORICO.exists():
            raise RuntimeError(f"Falta {cfg.RUTA_HISTORICO.name} en la carpeta del proyecto.")
        self.df = pd.read_csv(cfg.RUTA_HISTORICO, parse_dates=["timestamp"])
        self.pos = 0
        self.escenario, self.esc_inicio = None, None
        self.contador = 0                      # minutos simulados (avanza en cualquier modo)
        self.modo = None                       # funcionamiento forzado: clave de MODOS o None (calendario real)
        self.reloj = None
        # Minutos normales del primer semestre por modo de operación, para el modo demostración
        sano = self.df[(self.df["LABEL_Estado_Planta"] == "Normal") & (self.df["timestamp"] < "2026-07-01")]
        self.pools = {}
        for clave, (estado, tipo) in MODOS.items():
            p = sano[(sano["ESTADO_operacion"] == estado) & (sano["TIPO_asfalto"] == tipo)]
            self.pools[clave] = p.reset_index(drop=True)
        self.pool_pos = {k: 0 for k in MODOS}
        self.rng = np.random.default_rng(7)
        etq = self.df["LABEL_Estado_Planta"]
        nuevo = (etq != "Normal") & (etq != etq.shift())
        ev = self.df.loc[nuevo, ["timestamp", "LABEL_Estado_Planta"]]
        ev = ev[ev["timestamp"].diff().isna() | (ev["timestamp"].diff() > pd.Timedelta(hours=24)) |
                (ev["LABEL_Estado_Planta"] != ev["LABEL_Estado_Planta"].shift())]
        self.episodios = [{"indice": int(i), "estado": e, "inicio": t.strftime("%d-%m-%Y %H:%M")}
                          for i, t, e in zip(ev.index, ev["timestamp"], ev["LABEL_Estado_Planta"])]

    @property
    def tiempo(self):
        return self.reloj if self.modo else self.df["timestamp"].iloc[self.pos]

    def forzar(self, modo):
        """Fija un modo de funcionamiento (demostración) o vuelve al calendario real con None."""
        if modo and modo not in MODOS:
            raise ValueError(modo)
        if modo and not self.modo:
            self.reloj = self.df["timestamp"].iloc[self.pos]
        self.modo = modo

    def ir_a(self, indice):
        self.pos = int(np.clip(indice, 0, len(self.df) - 1))

    def activar(self, escenario):
        self.escenario = escenario
        self.esc_inicio = self.contador if escenario else None

    def historia(self):
        return self.df.iloc[:self.pos]

    def _bloque_forzado(self, n):
        pool = self.pools[self.modo]
        i = self.pool_pos[self.modo]
        idx = (np.arange(i, i + n)) % len(pool)
        self.pool_pos[self.modo] = int((i + n) % len(pool))
        b = pool.iloc[idx].copy()
        b["timestamp"] = self.reloj + pd.to_timedelta(np.arange(1, n + 1), unit="min")
        b.index = np.arange(self.contador, self.contador + n) + 10_000_000      # índice único
        self.reloj = b["timestamp"].iloc[-1]
        return b

    def siguiente(self, n):
        if self.modo:
            bloque = self._bloque_forzado(n)
        else:
            fin = min(self.pos + n, len(self.df))
            bloque = self.df.iloc[self.pos:fin].copy()
            n = len(bloque)
        if self.escenario:
            self._aplicar(bloque, self.contador + np.arange(len(bloque)) - self.esc_inicio)
            bloque["LABEL_Estado_Planta"] = np.where(bloque["LABEL_Estado_Planta"] == "Normal",
                                                     f"Simulado: {self.escenario['nombre']}", bloque["LABEL_Estado_Planta"])
        self.contador += len(bloque)
        if not self.modo:
            self.pos = fin if fin < len(self.df) else 0
        return bloque

    def _aplicar(self, b, minutos):
        e = self.escenario
        prog = np.ones(len(b)) if e["evolucion"] == "inmediata" else np.clip(minutos / e["minutos"], 0, 1)
        marcha = b["ESTADO_operacion"].isin(cfg.ESTADOS_MARCHA).values
        plasto_prod = (b["ESTADO_operacion"] == "Produccion").values & (b["TIPO_asfalto"] == "Plastomerico").values
        for ef in e["efectos"]:
            s, op, val = ef["sensor"], ef["operacion"], ef["valor"]
            if s not in b:
                continue
            aplica = plasto_prod if s in cfg.SOLO_PLASTOMERICO else (marcha if s in cfg.SOLO_MARCHA else np.ones(len(b), bool))
            x = b[s].values.astype(float)
            objetivo = {"fijar": np.full(len(b), val), "sumar": x + val, "multiplicar": x * val}[op]
            b[s] = np.where(aplica, x + (objetivo - x) * prog, x)
        # variables derivadas, para que el escenario sea físicamente coherente
        tb = b["TEM_son_betum_in"]
        ok = b["VOLT_son_betum_in"] > 1
        b.loc[ok, "RES_son_betum_in"] = 100 * (1 + 0.00385 * tb[ok])
        b.loc[ok, "AMP_son_betum_in"] = 4 + 16 * tb[ok] / 250
        b["RES_son_solucion_in"] = 100 * (1 + 0.00385 * b["TEM_son_solucion_in"])
        b["AMP_son_solucion_in"] = 4 + 16 * b["TEM_son_solucion_in"] / 100
        b["EST_niv_betum_dep"] = (b["AMP_eco_betum_dep"] < 23).astype(float)
        b["AMP_vib_motor_molino"] = 4 + 0.64 * b["VIB_vel_motor_molino"]

    def info(self):
        e = self.escenario
        out = {"posicion": self.pos, "total": len(self.df), "escenario": e["nombre"] if e else None, "modo": self.modo}
        if e:
            trans = self.contador - self.esc_inicio
            out["progreso"] = 1.0 if e["evolucion"] == "inmediata" else float(min(1, trans / e["minutos"]))
            out["minutos_desde_inicio"] = int(trans)
        return out
