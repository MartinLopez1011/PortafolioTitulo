"""Configuración del monitor del molino coloidal (Química Latinoamericana)."""
from pathlib import Path

BASE = Path(__file__).parent
EMPRESA, EQUIPO, PLANTA = "Química Latinoamericana", "Molino coloidal MC-01", "Planta de emulsión asfáltica"

# --- Archivos (exportados desde los notebooks de Colab) ------------------------
RUTA_HISTORICO = next((p for p in (BASE / "Dataset_Molino_QLA_Realista.zip", BASE / "Dataset_Molino_QLA_Realista.csv") if p.exists()),
                      BASE / "Dataset_Molino_QLA_Realista.zip")
RUTA_BITACORA = BASE / "Bitacora_Mantenimiento_QLA.csv"
RUTA_IDENTIFICACION = BASE / "config_modelo.joblib"           # notebook de identificación (LightGBM / MLP / ...)
RUTA_AE = BASE / "autoencoder_molino_QLA.keras"               # notebook del autoencoder
RUTA_AE_CONFIG = BASE / "autoencoder_molino_config.joblib"
RUTA_PREDICTIVO = BASE / "modelo_predictivo.joblib"            # notebook de predicción
RUTA_DB = BASE / "registro.db"

ESTADOS_MARCHA = ("Produccion", "Limpieza")

# --- Sensores: id -> (nombre, unidad, equipo) ---------------------------------
SENSORES = {
    "TEM_son_betum_in": ("Temperatura betún", "°C", "TK-101"),
    "RES_son_betum_in": ("Resistencia Pt100 betún", "Ω", "TK-101"),
    "VOLT_son_betum_in": ("Alimentación Pt100", "V", "TK-101"),
    "AMP_son_betum_in": ("Lazo Pt100 betún", "mA", "TK-101"),
    "AMP_eco_betum_dep": ("Eco radar", "dB", "TK-101"),
    "EST_niv_betum_dep": ("Estado NAMUR radar", "", "TK-101"),
    "POR_niv_betum_dep": ("Nivel", "%", "TK-101"),
    "AMP_cau_betum_in": ("Lazo caudal betún", "mA", "FT-101"),
    "FRE_cau_betum_in": ("Frecuencia Coriolis", "Hz", "FT-101"),
    "CAU_bomba_lpm": ("Caudal bomba", "L/min", "F-101"),
    "PRE_dif_filtro_bar": ("Presión diferencial", "bar", "F-101"),
    "POS_valvula_3vias": ("Posición válvula", "", "V-101"),
    "VAL_aire_linea": ("Línea de aire", "", "V-101"),
    "TEM_son_solucion_in": ("Temperatura solución", "°C", "TK-201"),
    "RES_son_solucion_in": ("Resistencia Pt100 solución", "Ω", "TK-201"),
    "AMP_son_solucion_in": ("Lazo Pt100 solución", "mA", "TK-201"),
    "AMP_eco_solucion_dep": ("Eco radar", "dB", "TK-201"),
    "POR_niv_solucion_dep": ("Nivel", "%", "TK-201"),
    "AMP_cau_solucion_in": ("Lazo caudal solución", "mA", "FT-201"),
    "FRE_cau_solucion_in": ("Frecuencia Coriolis", "Hz", "FT-201"),
    "RPM_motor_molino": ("Velocidad", "RPM", "MC-01"),
    "FRE_vfd_motor_molino": ("Frecuencia variador", "Hz", "MC-01"),
    "AMP_vfd_motor_molino": ("Corriente motor", "A", "MC-01"),
    "TOR_vfd_motor_molino": ("Torque", "%", "MC-01"),
    "VIB_vel_motor_molino": ("Vibración", "mm/s", "MC-01"),
    "AMP_vib_motor_molino": ("Lazo vibración", "mA", "MC-01"),
    "TEM_emulsion_molino_out": ("Temperatura salida molino", "°C", "MC-01"),
    "PRE_intercambiador_bar": ("Presión", "bar", "E-301"),
    "TEM_son_emulsion_out": ("Temperatura emulsión", "°C", "TK-301"),
    "RES_son_emulsion_out": ("Resistencia Pt100 emulsión", "Ω", "TK-301"),
    "AMP_cau_emulsion_out": ("Lazo caudal emulsión", "mA", "TK-301"),
    "FRE_cau_emulsion_out": ("Frecuencia Coriolis emulsión", "Hz", "TK-301"),
    "AMP_eco_emulsion_dep": ("Eco radar", "dB", "TK-301"),
    "DIS_niv_emulsion_dep": ("Distancia radar", "m", "TK-301"),
}

# Señales que solo cambian con el molino en marcha (para los escenarios simulados)
SOLO_MARCHA = {"AMP_vfd_motor_molino", "TOR_vfd_motor_molino", "VIB_vel_motor_molino", "RPM_motor_molino",
               "CAU_bomba_lpm", "PRE_dif_filtro_bar", "TEM_emulsion_molino_out", "FRE_cau_emulsion_out"}
SOLO_PLASTOMERICO = {"PRE_intercambiador_bar"}

# --- Fallas ---------------------------------------------------------------------
FALLAS = {
    "Normal": dict(titulo="Operación normal", nivel="normal", prioridad=None, accion="Continuar monitoreo."),
    "Detenida": dict(titulo="Molino detenido", nivel="normal", prioridad=None, accion="Las calderas mantienen la temperatura."),
    "Sobrecarga_Motor_Por_Asfalto_Frio": dict(titulo="Sobrecarga del motor por asfalto frío", nivel="alerta", prioridad="alta",
        accion="Revisar caldera y calefacción de TK-101 antes de seguir cargando el molino."),
    "Filtro_Obstruido": dict(titulo="Filtro obstruido", nivel="alerta", prioridad="alta",
        accion="Limpiar el filtro F-101: la presión diferencial supera el límite y cae el caudal."),
    "Advertencia_Radar_Sucio_Betun": dict(titulo="Radar del estanque de betún sucio", nivel="aviso", prioridad="media",
        accion="Programar limpieza de la antena del radar de TK-101."),
    "Cortocircuito_Transmisor_Caudal_Sol": dict(titulo="Cortocircuito en transmisor de caudal de solución", nivel="alerta", prioridad="alta",
        accion="Revisar el lazo 4–20 mA de FT-201: la señal está saturada."),
    "Falla_Electrica_PT100_Betun": dict(titulo="Falla eléctrica en Pt100 del betún", nivel="alerta", prioridad="alta",
        accion="Revisar alimentación de 24 V y borneras de la Pt100 de TK-101."),
    "Ensuciamiento_Intercambiador": dict(titulo="Intercambiador sucio", nivel="aviso", prioridad="media",
        accion="Programar limpieza química del intercambiador E-301."),
    "Desgaste_Rodamientos_Molino": dict(titulo="Desgaste de rodamientos del molino", nivel="alerta", prioridad="alta",
        accion="Programar cambio de rodamientos del molino MC-01."),
    "Anomalia_Desconocida": dict(titulo="Comportamiento anómalo no clasificado", nivel="desconocida", prioridad="media",
        accion="El molino se aleja de su comportamiento sano. Revisar los sensores señalados."),
}
CORTO = {"Sobrecarga_Motor_Por_Asfalto_Frio": "Sobrecarga", "Filtro_Obstruido": "Filtro",
         "Advertencia_Radar_Sucio_Betun": "Radar sucio", "Cortocircuito_Transmisor_Caudal_Sol": "Cortocircuito",
         "Falla_Electrica_PT100_Betun": "Pt100", "Ensuciamiento_Intercambiador": "Intercambiador",
         "Desgaste_Rodamientos_Molino": "Rodamientos"}

# El autoencoder se usa como alarma solo si LightGBM dice "Normal" y los sensores más
# afectados corresponden a una falla rara que el modelo supervisado casi no conoce.
FIRMA_FALLAS_RARAS = {
    "Desgaste_Rodamientos_Molino": {"VIB_vel_motor_molino", "AMP_vib_motor_molino"},
    "Advertencia_Radar_Sucio_Betun": {"AMP_eco_betum_dep", "EST_niv_betum_dep"},
    "Ensuciamiento_Intercambiador": {"PRE_intercambiador_bar"},
}

# --- Reglas fijas (instrumentos y límites de proceso) -----------------------------
# (sensor, condición, valor, título, prioridad, solo con molino en marcha)
REGLAS = [
    ("AMP_cau_solucion_in", ">", 21.0, "Lazo de caudal de solución sobre 21 mA (NAMUR)", "alta", False),
    ("VOLT_son_betum_in", "<", 20.0, "Pt100 del betún sin alimentación", "alta", False),
    ("AMP_cau_emulsion_out", "<", 3.6, "Lazo de caudal de emulsión bajo 3,6 mA (NAMUR)", "alta", False),
    ("VIB_vel_motor_molino", ">", 4.5, "Vibración del molino sobre 4,5 mm/s", "alta", True),
    ("PRE_dif_filtro_bar", ">", 1.1, "Presión diferencial del filtro sobre 1,1 bar", "media", True),
    ("AMP_vfd_motor_molino", ">", 130.0, "Corriente del motor sobre 130 A", "alta", True),
]
PERSISTENCIA_ACTIVAR, PERSISTENCIA_VENTANA, PERSISTENCIA_RESOLVER = 3, 5, 1

# --- Indicadores -------------------------------------------------------------------
RANGO_CAUDAL_LPM = {"betun": 200.0, "solucion": 120.0}       # caudal a 20 mA de cada Coriolis
RELACION_OBJETIVO = (60.0, 68.0)
VOLTAJE_MOTOR_V, FACTOR_POTENCIA = 380.0, 0.85
MINUTOS_TURNO = 9 * 60

# --- Equipos que se pueden intervenir desde el dashboard ----------------------------
# clave del predictor -> (nombre del equipo en la bitácora, descripción por defecto)
INTERVENCIONES_UI = {
    "filtro": ("F-101 filtro de línea", "Limpieza de filtro"),
    "radar": ("TK-101 radar de nivel", "Limpieza de antena del radar"),
    "caldera": ("TK-101 caldera / calefactor de betún", "Mantención de caldera"),
    "intercambiador": ("E-301 intercambiador de calor", "Limpieza química del intercambiador"),
    "caudalimetro": ("FT-201 caudalímetro solución", "Secado y sellado del transmisor de caudal"),
    "pt100": ("TT-101 Pt100 betún", "Reapriete y limpieza de borneras de la Pt100"),
    "rodamientos": ("MC-01 rodamientos del molino", "Cambio de rodamientos del molino"),
}
# falla -> equipo a intervenir
EQUIPO_DE_FALLA = {"Filtro_Obstruido": "filtro", "Advertencia_Radar_Sucio_Betun": "radar",
                   "Sobrecarga_Motor_Por_Asfalto_Frio": "caldera", "Ensuciamiento_Intercambiador": "intercambiador",
                   "Cortocircuito_Transmisor_Caudal_Sol": "caudalimetro", "Falla_Electrica_PT100_Betun": "pt100",
                   "Desgaste_Rodamientos_Molino": "rodamientos"}
