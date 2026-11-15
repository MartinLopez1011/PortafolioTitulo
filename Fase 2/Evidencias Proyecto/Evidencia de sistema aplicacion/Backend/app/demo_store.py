"""Datos de demostración para operar el dashboard localmente sin conexión a Supabase/PostgreSQL.

Permite probar el Frontend, los gráficos, el panel de control y la recepción MQTT en tiempo real
vía WebSockets (AWS IoT Core) aun cuando la base de datos externa no esté disponible.
"""
import datetime
from typing import Dict, List, Any

# Usuario administrador de prueba predeterminado
USUARIOS = {
    "admin@demo.qla.cl": {
        "id": 1,
        "nombre": "Administrador QLA",
        "email": "admin@demo.qla.cl",
        "password_hash": "$2b$10$wE9K2.6q5K7H8Y8Z8Y8Z8e8Y8Z8Y8Z8Y8Z8Y8Z8Y8Z8Y8Z8Y8Z8Y8", # Dummy
        "rol": "administrador",
        "nivel": 4,
        "debe_cambiar_clave": False,
        "activo": True
    },
    "operador@demo.qla.cl": {
        "id": 2,
        "nombre": "Operador de Turno",
        "email": "operador@demo.qla.cl",
        "password_hash": "$2b$10$wE9K2.6q5K7H8Y8Z8Y8Z8e8Y8Z8Y8Z8Y8Z8Y8Z8Y8Z8Y8Z8Y8Z8Y8",
        "rol": "operador",
        "nivel": 2,
        "debe_cambiar_clave": False,
        "activo": True
    }
}

EQUIPOS = [
    {
        "id": 1,
        "codigo": "MC-01",
        "nombre": "Molino coloidal HP 240",
        "tipo": "Molino coloidal de emulsión",
        "marca": "Siefer",
        "modelo": "SM 240",
        "potencia": "100 hp, 2.900 RPM",
        "ubicacion": "Planta de emulsiones, El Salto"
    }
]

TIPOS_FALLA = [
    {"id": 1, "codigo": "Sobrecarga_Motor_Por_Asfalto_Frio", "titulo": "Sobrecarga del motor por asfalto frío", "componente": "TK-101", "prioridad": "alta", "accion": "Revisar caldera y calefacción de TK-101."},
    {"id": 2, "codigo": "Filtro_Obstruido", "titulo": "Filtro obstruido", "componente": "F-101", "prioridad": "alta", "accion": "Limpiar filtro F-101: presión diferencial alta."},
    {"id": 3, "codigo": "Advertencia_Radar_Sucio_Betun", "titulo": "Radar de betún sucio", "componente": "TK-101", "prioridad": "media", "accion": "Programar limpieza de la antena del radar."},
    {"id": 4, "codigo": "Cortocircuito_Transmisor_Caudal_Sol", "titulo": "Cortocircuito en transmisor de solución", "componente": "FT-201", "prioridad": "alta", "accion": "Revisar lazo 4-20 mA de FT-201."},
    {"id": 5, "codigo": "Falla_Electrica_PT100_Betun", "titulo": "Falla eléctrica en Pt100 del betún", "componente": "TT-101", "prioridad": "alta", "accion": "Revisar alimentación y borneras de Pt100."},
    {"id": 6, "codigo": "Ensuciamiento_Intercambiador", "titulo": "Intercambiador sucio", "componente": "E-301", "prioridad": "media", "accion": "Programar limpieza química de E-301."},
    {"id": 7, "codigo": "Desgaste_Rodamientos_Molino", "titulo": "Desgaste de rodamientos del molino", "componente": "MC-01", "prioridad": "alta", "accion": "Programar cambio de rodamientos de MC-01."},
    {"id": 8, "codigo": "Anomalia_Desconocida", "titulo": "Comportamiento anómalo no clasificado", "componente": "MC-01", "prioridad": "media", "accion": "El molino se aleja de su comportamiento sano."}
]

# Catálogo completo de sensores para MC-01
SENSORES = [
    {"id": 1, "tag": "TEM_son_betum_in", "nombre": "Temperatura betún", "componente": "TK-101", "variable": "temperatura", "tipo_sensor": "Pt100 TT-101", "unidad": "°C", "rango_min": 0, "rango_max": 200, "normal_min": 130, "normal_max": 160, "senal": "4-20 mA", "origen": "real", "activo": True},
    {"id": 2, "tag": "RES_son_betum_in", "nombre": "Resistencia Pt100 betún", "componente": "TK-101", "variable": "resistencia", "tipo_sensor": "Pt100 TT-101", "unidad": "Ω", "rango_min": 0, "rango_max": 300, "normal_min": 145, "normal_max": 165, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 3, "tag": "VOLT_son_betum_in", "nombre": "Voltaje alimentación Pt100", "componente": "TK-101", "variable": "voltaje", "tipo_sensor": "Fuente 24V", "unidad": "V", "rango_min": 0, "rango_max": 30, "normal_min": 23, "normal_max": 25, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 4, "tag": "AMP_son_betum_in", "nombre": "Lazo Pt100 betún", "componente": "TK-101", "variable": "corriente_lazo", "tipo_sensor": "Transmisor TT-101", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 5, "tag": "AMP_cau_betum_in", "nombre": "Lazo caudal betún", "componente": "FT-101", "variable": "corriente_lazo", "tipo_sensor": "Coriolis FT-101", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 6, "tag": "FRE_cau_betum_in", "nombre": "Frecuencia Coriolis betún", "componente": "FT-101", "variable": "frecuencia", "tipo_sensor": "Coriolis FT-101", "unidad": "Hz", "rango_min": 0, "rango_max": 600, "normal_min": 220, "normal_max": 560, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 7, "tag": "AMP_eco_betum_dep", "nombre": "Eco radar betún", "componente": "TK-101", "variable": "eco", "tipo_sensor": "Radar TK-101", "unidad": "dB", "rango_min": 0, "rango_max": 100, "normal_min": 25, "normal_max": 80, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 8, "tag": "EST_niv_betum_dep", "nombre": "Estado NAMUR radar betún", "componente": "TK-101", "variable": "estado", "tipo_sensor": "Radar TK-101", "unidad": "0/1/2", "rango_min": 0, "rango_max": 2, "normal_min": 0, "normal_max": 0, "senal": "digital", "origen": "simulado", "activo": True},
    {"id": 9, "tag": "TEM_son_solucion_in", "nombre": "Temperatura solución", "componente": "TK-201", "variable": "temperatura", "tipo_sensor": "Pt100 TT-201", "unidad": "°C", "rango_min": 0, "rango_max": 100, "normal_min": 32, "normal_max": 62, "senal": "4-20 mA", "origen": "real", "activo": True},
    {"id": 10, "tag": "RES_son_solucion_in", "nombre": "Resistencia Pt100 solución", "componente": "TK-201", "variable": "resistencia", "tipo_sensor": "Pt100 TT-201", "unidad": "Ω", "rango_min": 0, "rango_max": 200, "normal_min": 112, "normal_max": 125, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 11, "tag": "AMP_son_solucion_in", "nombre": "Lazo Pt100 solución", "componente": "TK-201", "variable": "corriente_lazo", "tipo_sensor": "Transmisor TT-201", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 12, "tag": "AMP_cau_solucion_in", "nombre": "Lazo caudal solución", "componente": "FT-201", "variable": "corriente_lazo", "tipo_sensor": "Coriolis FT-201", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 13, "tag": "FRE_cau_solucion_in", "nombre": "Frecuencia Coriolis solución", "componente": "FT-201", "variable": "frecuencia", "tipo_sensor": "Coriolis FT-201", "unidad": "Hz", "rango_min": 0, "rango_max": 800, "normal_min": 350, "normal_max": 700, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 14, "tag": "AMP_eco_solucion_dep", "nombre": "Eco radar solución", "componente": "TK-201", "variable": "eco", "tipo_sensor": "Radar TK-201", "unidad": "dB", "rango_min": 0, "rango_max": 100, "normal_min": 25, "normal_max": 85, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 15, "tag": "TEM_son_emulsion_out", "nombre": "Temperatura emulsión", "componente": "TK-301", "variable": "temperatura", "tipo_sensor": "Pt100 TT-301", "unidad": "°C", "rango_min": 0, "rango_max": 120, "normal_min": 70, "normal_max": 96, "senal": "4-20 mA", "origen": "real", "activo": True},
    {"id": 16, "tag": "RES_son_emulsion_out", "nombre": "Resistencia Pt100 emulsión", "componente": "TK-301", "variable": "resistencia", "tipo_sensor": "Pt100 TT-301", "unidad": "Ω", "rango_min": 0, "rango_max": 200, "normal_min": 125, "normal_max": 138, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 17, "tag": "AMP_cau_emulsion_out", "nombre": "Lazo caudal emulsión", "componente": "TK-301", "variable": "corriente_lazo", "tipo_sensor": "Coriolis emulsión", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 18, "tag": "FRE_cau_emulsion_out", "nombre": "Frecuencia Coriolis emulsión", "componente": "TK-301", "variable": "frecuencia", "tipo_sensor": "Coriolis emulsión", "unidad": "Hz", "rango_min": 0, "rango_max": 1000, "normal_min": 280, "normal_max": 920, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 19, "tag": "AMP_eco_emulsion_dep", "nombre": "Eco radar emulsión", "componente": "TK-301", "variable": "eco", "tipo_sensor": "Radar TK-301", "unidad": "dB", "rango_min": 0, "rango_max": 100, "normal_min": 25, "normal_max": 80, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 20, "tag": "RPM_motor_molino", "nombre": "Velocidad del motor", "componente": "MC-01", "variable": "velocidad", "tipo_sensor": "Variador MC-01", "unidad": "RPM", "rango_min": 0, "rango_max": 3200, "normal_min": 2850, "normal_max": 3000, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 21, "tag": "FRE_vfd_motor_molino", "nombre": "Frecuencia variador", "componente": "MC-01", "variable": "frecuencia", "tipo_sensor": "Variador MC-01", "unidad": "Hz", "rango_min": 0, "rango_max": 60, "normal_min": 48, "normal_max": 52, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 22, "tag": "AMP_vfd_motor_molino", "nombre": "Corriente del motor", "componente": "MC-01", "variable": "corriente", "tipo_sensor": "Variador MC-01", "unidad": "A", "rango_min": 0, "rango_max": 150, "normal_min": 55, "normal_max": 115, "senal": "directa", "origen": "real", "activo": True},
    {"id": 23, "tag": "TOR_vfd_motor_molino", "nombre": "Torque del motor", "componente": "MC-01", "variable": "torque", "tipo_sensor": "Variador MC-01", "unidad": "%", "rango_min": 0, "rango_max": 150, "normal_min": 60, "normal_max": 95, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 24, "tag": "VIB_vel_motor_molino", "nombre": "Vibración del motor", "componente": "MC-01", "variable": "vibracion", "tipo_sensor": "Sensor de vibración", "unidad": "mm/s", "rango_min": 0, "rango_max": 10, "normal_min": 0.5, "normal_max": 3.2, "senal": "4-20 mA", "origen": "real", "activo": True},
    {"id": 25, "tag": "AMP_vib_motor_molino", "nombre": "Lazo vibración", "componente": "MC-01", "variable": "corriente_lazo", "tipo_sensor": "Sensor de vibración", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 26, "tag": "CAU_bomba_lpm", "nombre": "Caudal de la bomba", "componente": "P-101", "variable": "caudal", "tipo_sensor": "Bomba P-101", "unidad": "L/min", "rango_min": 0, "rango_max": 400, "normal_min": 140, "normal_max": 280, "senal": "directa", "origen": "simulado", "activo": True},
    {"id": 27, "tag": "PRE_dif_filtro_bar", "nombre": "Presión diferencial filtro", "componente": "F-101", "variable": "presion", "tipo_sensor": "Transmisor ΔP F-101", "unidad": "bar", "rango_min": 0, "rango_max": 2.5, "normal_min": 0.1, "normal_max": 0.8, "senal": "4-20 mA", "origen": "real", "activo": True},
    {"id": 28, "tag": "TEM_emulsion_molino_out", "nombre": "Temperatura salida molino", "componente": "MC-01", "variable": "temperatura", "tipo_sensor": "Sensor salida MC-01", "unidad": "°C", "rango_min": 0, "rango_max": 120, "normal_min": 70, "normal_max": 98, "senal": "4-20 mA", "origen": "simulado", "activo": True},
    {"id": 29, "tag": "PRE_intercambiador_bar", "nombre": "Presión intercambiador", "componente": "E-301", "variable": "presion", "tipo_sensor": "Transmisor E-301", "unidad": "bar", "rango_min": 0, "rango_max": 5.0, "normal_min": 0.0, "normal_max": 2.5, "senal": "4-20 mA", "origen": "simulado", "activo": True}
]

# Las 31 variables de entrada de los Modelos 1, 2 y 3 (29 sensores + 2 binarias de contexto)
SENSORES_29_MODELOS = [s["tag"] for s in SENSORES]
VARIABLES_CONTEXTO_2 = ["es_plastomerico", "en_limpieza"]
FEATURES_31_MODELOS = SENSORES_29_MODELOS + VARIABLES_CONTEXTO_2

# Las 11 variables que el Modelo 3 refactoriza a partir de las 31 para generar las 80 tabulares
VARIABLES_11_MODELO3 = [
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
    "EST_niv_betum_dep",
]

# Valores por defecto para lecturas en vivo (31 variables calibradas al régimen Produccion|Convencional)
VALORES_INICIALES = {
    "TEM_son_betum_in": 134.7,
    "RES_son_betum_in": 151.86,
    "VOLT_son_betum_in": 23.76,
    "AMP_son_betum_in": 12.62,
    "AMP_cau_betum_in": 12.3,
    "FRE_cau_betum_in": 249.5,
    "AMP_eco_betum_dep": 52.33,
    "EST_niv_betum_dep": 0.0,
    "TEM_son_solucion_in": 36.4,
    "RES_son_solucion_in": 114.01,
    "AMP_son_solucion_in": 9.82,
    "AMP_cau_solucion_in": 13.31,
    "FRE_cau_solucion_in": 400.0,
    "AMP_eco_solucion_dep": 70.0,
    "TEM_son_emulsion_out": 72.5,
    "RES_son_emulsion_out": 127.91,
    "AMP_cau_emulsion_out": 14.44,
    "FRE_cau_emulsion_out": 322.7,
    "AMP_eco_emulsion_dep": 60.0,
    "RPM_motor_molino": 2898.0,
    "FRE_vfd_motor_molino": 50.0,
    "AMP_vfd_motor_molino": 105.7,
    "TOR_vfd_motor_molino": 71.7,
    "VIB_vel_motor_molino": 2.47,
    "AMP_vib_motor_molino": 5.58,
    "CAU_bomba_lpm": 180.6,
    "PRE_dif_filtro_bar": 0.42,
    "TEM_emulsion_molino_out": 73.5,
    "PRE_intercambiador_bar": 0.0,
    "es_plastomerico": 0,
    "en_limpieza": 0
}


def obtener_lecturas_demo() -> List[Dict[str, Any]]:
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lecturas = []
    for s in SENSORES:
        v = VALORES_INICIALES.get(s["tag"], 0.0)
        fuera = False
        if s["normal_min"] is not None and v < s["normal_min"]:
            fuera = True
        if s["normal_max"] is not None and v > s["normal_max"]:
            fuera = True
        lecturas.append({
            "sensor_id": s["id"],
            "tag": s["tag"],
            "nombre": s["nombre"],
            "componente": s["componente"],
            "variable": s["variable"],
            "unidad": s["unidad"],
            "normal_min": s["normal_min"],
            "normal_max": s["normal_max"],
            "fuente": "simulado",
            "ts": ahora,
            "valor": v,
            "calidad": "buena",
            "fuera_de_rango": fuera
        })
    return lecturas


def obtener_resumen_demo() -> Dict[str, Any]:
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "estado": "produccion",
        "tipo_asfalto": "convencional",
        "ultima_lectura": ahora,
        "sensores_con_datos": len(SENSORES),
        "sensores_fuera_de_rango": 0,
        "alarmas_activas": 0,
        "alarmas_sin_reconocer": 0
    }


def obtener_predicciones_demo() -> List[Dict[str, Any]]:
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return [
        {
            "id": 1,
            "ts": ahora,
            "fuente": "simulado",
            "modelo": "predictivo",
            "modelo_version": "LightGBM_31_11_80",
            "horizonte": "24h",
            "falla": "Normal",
            "titulo": "Operación normal",
            "prob_falla": 0.04,
            "indice_salud": 96.0,
            "vida_util_horas": None,
            "alerta": False,
            "accion": "Operación dentro de parámetros nominales."
        },
        {
            "id": 2,
            "ts": ahora,
            "fuente": "simulado",
            "modelo": "predictivo",
            "modelo_version": "LightGBM_31_11_80",
            "horizonte": "5d",
            "falla": "Normal",
            "titulo": "Operación normal",
            "prob_falla": 0.08,
            "indice_salud": 92.0,
            "vida_util_horas": None,
            "alerta": False,
            "accion": "Monitoreo continuo activo."
        },
        {
            "id": 3,
            "ts": ahora,
            "fuente": "simulado",
            "modelo": "predictivo",
            "modelo_version": "Tendencia_31_11_80",
            "horizonte": "15d",
            "falla": "Desgaste_Rodamientos_Molino",
            "titulo": "Desgaste de rodamientos del molino",
            "prob_falla": 0.12,
            "indice_salud": 88.0,
            "vida_util_horas": 310.0,
            "alerta": False,
            "accion": "Vibración estable. Mantener lubricación preventiva."
        }
    ]


def obtener_historial_estado_demo() -> List[Dict[str, Any]]:
    t = datetime.datetime.now(datetime.timezone.utc)
    return [
        {
            "inicio": (t - datetime.timedelta(hours=24)).isoformat(),
            "fin": (t - datetime.timedelta(hours=6)).isoformat(),
            "estado": "produccion",
            "tipo_asfalto": "convencional",
            "minutos": 1080
        },
        {
            "inicio": (t - datetime.timedelta(hours=6)).isoformat(),
            "fin": (t - datetime.timedelta(hours=5)).isoformat(),
            "estado": "limpieza",
            "tipo_asfalto": "ninguno",
            "minutos": 60
        },
        {
            "inicio": (t - datetime.timedelta(hours=5)).isoformat(),
            "fin": t.isoformat(),
            "estado": "produccion",
            "tipo_asfalto": "convencional",
            "minutos": 300
        }
    ]


# =====================================================================
# SIMULADOR EN MEMORIA PARA MODO_DEMO=1 (sin PostgreSQL ni AWS)
# =====================================================================
import math as _math
import time as _time

SIM_ESTADO: Dict[str, Any] = {
    "corriendo": True,
    "velocidad": "1m",
    "saltar_paradas": True,
    "modo": "",
    "escenario": "filtro",  # Por defecto muestra el caso "Filtro obstruido" para apreciar alertas y barras
    "progreso": 0.85,
    "publicados": 142,
    "tiempo_base": datetime.datetime(2026, 9, 15, 14, 30, tzinfo=datetime.timezone.utc),
    "ultimo_tick": _time.time(),
}

ESCENARIOS_DEMO = [
    {"clave": "filtro", "nombre": "Filtro obstruyéndose", "categoria": "conocida",
     "falla": "Filtro_Obstruido", "titulo": "Filtro obstruido",
     "accion": "Limpiar o rotar canastillo del filtro F-101: presión diferencial alta.",
     "descripcion": "El filtro acumula sólidos: sube la presión diferencial y cae el caudal de la bomba."},
    {"clave": "caldera", "nombre": "Caldera perdiendo potencia", "categoria": "conocida",
     "falla": "Sobrecarga_Motor_Por_Asfalto_Frio", "titulo": "Sobrecarga del motor por asfalto frío",
     "accion": "Revisar caldera y calefacción de TK-101 (temperatura bajo 125 °C).",
     "descripcion": "El betún se enfría de a poco; al bajar de ~125 °C el motor entra en sobrecarga."},
    {"clave": "radar", "nombre": "Radar ensuciándose", "categoria": "conocida",
     "falla": "Advertencia_Radar_Sucio_Betun", "titulo": "Radar de betún sucio",
     "accion": "Programar limpieza de antena del radar de TK-101.",
     "descripcion": "Costra de asfalto en la antena del radar de TK-101: el eco se debilita."},
    {"clave": "cortocircuito", "nombre": "Cortocircuito caudalímetro", "categoria": "conocida",
     "falla": "Cortocircuito_Transmisor_Caudal_Sol", "titulo": "Cortocircuito en transmisor de solución",
     "accion": "Revisar lazo 4-20 mA de FT-201.",
     "descripcion": "El lazo de FT-201 se satura sobre 22 mA."},
    {"clave": "rodamientos", "nombre": "Rodamientos desgastándose", "categoria": "conocida",
     "falla": "Desgaste_Rodamientos_Molino", "titulo": "Desgaste de rodamientos del molino",
     "accion": "Programar cambio de rodamientos de MC-01 y verificar lubricación.",
     "descripcion": "Desgaste mecánico: la vibración del molino sube durante días."},
    {"clave": "cavitacion", "nombre": "Bomba cavitando", "categoria": "nueva",
     "falla": "Anomalia_Desconocida", "titulo": "Comportamiento anómalo no clasificado",
     "accion": "El molino se aleja de su comportamiento sano. Revisar succión de bomba P-101.",
     "descripcion": "Aire o vapor en la succión: el caudal cae y el autoencoder detecta la anomalía."},
]


def _avanzar_reloj_demo() -> datetime.datetime:
    ahora = _time.time()
    dt_s = max(0.0, ahora - SIM_ESTADO["ultimo_tick"])
    SIM_ESTADO["ultimo_tick"] = ahora
    if SIM_ESTADO["corriendo"]:
        paso_min = {"real": dt_s / 60.0, "1m": dt_s * 1.0, "10m": dt_s * 10.0, "1h": dt_s * 60.0}.get(
            SIM_ESTADO["velocidad"], dt_s
        )
        SIM_ESTADO["tiempo_base"] += datetime.timedelta(minutes=paso_min)
        SIM_ESTADO["publicados"] += max(1, int(dt_s))
        if SIM_ESTADO["escenario"]:
            SIM_ESTADO["progreso"] = min(1.0, SIM_ESTADO["progreso"] + 0.01)
    return SIM_ESTADO["tiempo_base"]


def obtener_simulacion_opciones_demo() -> Dict[str, Any]:
    return {
        "velocidades": [
            {"clave": "real", "texto": "Tiempo real"},
            {"clave": "1m", "texto": "1 minuto por segundo"},
            {"clave": "10m", "texto": "10 minutos por segundo"},
            {"clave": "1h", "texto": "1 hora por segundo"},
        ],
        "modos": [
            {"clave": "produccion_convencional", "texto": "Producción convencional"},
            {"clave": "produccion_plastomerico", "texto": "Producción plastomérico"},
            {"clave": "limpieza", "texto": "Limpieza de línea"},
            {"clave": "detenida", "texto": "Planta detenida"},
        ],
        "escenarios": ESCENARIOS_DEMO,
        "ir_a": {
            "meses": [
                {"fecha": "2026-03-01T08:00:00Z", "etiqueta": "Marzo 2026"},
                {"fecha": "2026-06-01T08:00:00Z", "etiqueta": "Junio 2026"},
                {"fecha": "2026-09-01T08:40:00Z", "etiqueta": "Septiembre 2026"},
            ],
            "antes_de_falla": [
                {"fecha": "2026-09-15T14:00:00Z", "etiqueta": "Antes de obstrucción de filtro F-101"},
                {"fecha": "2026-10-04T10:00:00Z", "etiqueta": "Antes de sobrecarga por asfalto frío"},
            ],
        },
    }


def obtener_simulacion_estado_demo() -> Dict[str, Any]:
    ts = _avanzar_reloj_demo()
    esc_obj = next((e for e in ESCENARIOS_DEMO if e["clave"] == SIM_ESTADO["escenario"]), None)
    return {
        "corriendo": SIM_ESTADO["corriendo"],
        "preparando": None,
        "velocidad": SIM_ESTADO["velocidad"],
        "saltar_paradas": SIM_ESTADO["saltar_paradas"],
        "modo": SIM_ESTADO["modo"] or None,
        "escenario": {"clave": esc_obj["clave"], "nombre": esc_obj["nombre"], "progreso": SIM_ESTADO["progreso"]} if esc_obj else None,
        "tiempo": ts.isoformat(),
        "publicacion": "local",
        "publicados": SIM_ESTADO["publicados"],
        "recolectados": SIM_ESTADO["publicados"],
        "pendientes": 0,
        "descartados": 0,
        "etiqueta_real": esc_obj["falla"] if esc_obj else "Normal",
        "aviso": None,
        "error": None,
    }


def controlar_simulacion_demo(accion: str, valor: str | None) -> Dict[str, Any]:
    if accion == "iniciar":
        SIM_ESTADO["corriendo"] = True
    elif accion == "pausar":
        SIM_ESTADO["corriendo"] = False
    elif accion == "velocidad" and valor:
        SIM_ESTADO["velocidad"] = valor
    elif accion == "saltar_paradas":
        SIM_ESTADO["saltar_paradas"] = valor == "1"
    elif accion == "modo":
        SIM_ESTADO["modo"] = valor or ""
    elif accion == "escenario":
        SIM_ESTADO["escenario"] = valor or ""
        SIM_ESTADO["progreso"] = 0.75 if valor else 0.0
    elif accion == "ir_a" and valor:
        try:
            SIM_ESTADO["tiempo_base"] = datetime.datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except Exception:
            pass
    return obtener_simulacion_estado_demo()


def obtener_proceso_demo() -> Dict[str, Any]:
    ts = _avanzar_reloj_demo()
    modo_cfg = {
        "": ("produccion", "convencional"),
        "produccion_convencional": ("produccion", "convencional"),
        "produccion_plastomerico": ("produccion", "plastomerico"),
        "limpieza": ("limpieza", "convencional"),
        "detenida": ("detenida", "ninguno"),
    }.get(SIM_ESTADO["modo"], ("produccion", "convencional"))
    estado, tipo_asfalto = modo_cfg
    en_marcha = estado in ("produccion", "limpieza")

    esc = SIM_ESTADO["escenario"]
    osc = _math.sin(_time.time() / 4.0)
    valores = dict(VALORES_INICIALES)
    valores["TEM_son_betum_in"] = round(146.0 + osc * 1.4, 1)
    valores["TEM_son_solucion_in"] = round(46.2 + osc * 0.6, 1)
    valores["AMP_vfd_motor_molino"] = round(98.4 + osc * 2.1, 1) if en_marcha else 0.0
    valores["TOR_vfd_motor_molino"] = round(76.0 + osc * 1.5, 0) if en_marcha else 0.0
    valores["VIB_vel_motor_molino"] = round(2.35 + osc * 0.12, 2) if en_marcha else 0.0
    valores["RPM_motor_molino"] = round(2905.0 + osc * 6.0, 0) if en_marcha else 0.0
    valores["TEM_emulsion_molino_out"] = round(86.5 + osc * 0.8, 1) if en_marcha else 25.0
    valores["CAU_bomba_lpm"] = round(192.0 + osc * 3.0, 0) if en_marcha else 0.0
    valores["PRE_dif_filtro_bar"] = round(0.44 + abs(osc) * 0.05, 2) if en_marcha else 0.0
    valores["PRE_intercambiador_bar"] = round(1.15 + abs(osc) * 0.08, 2) if tipo_asfalto == "plastomerico" and en_marcha else 0.1
    valores["AMP_eco_betum_dep"] = round(54.2 + osc * 1.0, 1)
    valores["POR_niv_betum_dep"] = 72.0
    valores["POR_niv_solucion_dep"] = 64.0
    valores["AMP_niv_emulsion_dep"] = 13.4

    senalados_ae = set()
    error_ae = 0.038
    umbral_ae = 0.120

    if en_marcha and esc == "filtro":
        valores["PRE_dif_filtro_bar"] = 1.48
        valores["CAU_bomba_lpm"] = 132.0
        senalados_ae = {"PRE_dif_filtro_bar", "CAU_bomba_lpm"}
        error_ae = 0.214
    elif en_marcha and esc == "caldera":
        valores["TEM_son_betum_in"] = 118.4
        valores["AMP_vfd_motor_molino"] = 126.5
        valores["TOR_vfd_motor_molino"] = 99.0
        senalados_ae = {"TEM_son_betum_in", "AMP_vfd_motor_molino", "TOR_vfd_motor_molino"}
        error_ae = 0.265
    elif en_marcha and esc == "radar":
        valores["AMP_eco_betum_dep"] = 16.5
        senalados_ae = {"AMP_eco_betum_dep"}
        error_ae = 0.145
    elif en_marcha and esc == "cortocircuito":
        valores["AMP_cau_solucion_in"] = 22.5
        senalados_ae = {"AMP_cau_solucion_in"}
        error_ae = 0.310
    elif en_marcha and esc == "rodamientos":
        valores["VIB_vel_motor_molino"] = 4.65
        valores["AMP_vfd_motor_molino"] = 116.2
        senalados_ae = {"VIB_vel_motor_molino", "AMP_vfd_motor_molino"}
        error_ae = 0.240
    elif en_marcha and esc == "cavitacion":
        valores["CAU_bomba_lpm"] = 144.0
        valores["FRE_cau_emulsion_out"] = 395.0
        senalados_ae = {"CAU_bomba_lpm", "FRE_cau_emulsion_out"}
        error_ae = 0.228

    sensores_out = []
    for s in SENSORES:
        tag = s["tag"]
        v = valores.get(tag, 0.0)
        lo, hi = s["normal_min"], s["normal_max"]
        fuera = en_marcha and ((lo is not None and v < lo) or (hi is not None and v > hi))
        sensores_out.append({
            "tag": tag,
            "nombre": s["nombre"],
            "componente": s["componente"],
            "variable": s["variable"],
            "unidad": s["unidad"],
            "rango_min": s["rango_min"],
            "rango_max": s["rango_max"],
            "normal_min": lo,
            "normal_max": hi,
            "ts": ts.isoformat(),
            "valor": v,
            "fuera_de_rango": fuera,
            "senalado_ae": tag in senalados_ae,
        })
    # Niveles de tanques para el P&ID
    sensores_out.append({"tag": "POR_niv_betum_dep", "nombre": "Nivel betún", "unidad": "%", "rango_min": 0, "rango_max": 100, "normal_min": 15, "normal_max": 95, "valor": 72.0, "fuera_de_rango": False, "senalado_ae": False})
    sensores_out.append({"tag": "POR_niv_solucion_dep", "nombre": "Nivel solución", "unidad": "%", "rango_min": 0, "rango_max": 100, "normal_min": 15, "normal_max": 95, "valor": 64.0, "fuera_de_rango": False, "senalado_ae": False})
    sensores_out.append({"tag": "AMP_niv_emulsion_dep", "nombre": "Nivel emulsión", "unidad": "mA", "rango_min": 4, "rango_max": 20, "normal_min": 4, "normal_max": 20, "valor": 13.4, "fuera_de_rango": False, "senalado_ae": False})

    esc_obj = next((e for e in ESCENARIOS_DEMO if e["clave"] == esc), None) if en_marcha else None
    alarmas_activas = []
    if esc_obj:
        inicio_al = (ts - datetime.timedelta(minutes=18)).isoformat()
        alarmas_activas.append({
            "id": 101,
            "inicio": inicio_al,
            "fin": None,
            "activa": True,
            "mensaje": esc_obj["titulo"],
            "prioridad": "media" if esc == "cavitacion" else "alta",
            "origen": "modelo",
            "origen_texto": "autoencoder" if esc == "cavitacion" else "modelo de diagnóstico LightGBM",
            "falla": esc_obj["falla"],
            "regla": None,
            "componente": "F-101" if esc == "filtro" else "MC-01",
            "accion": esc_obj["accion"],
            "valor": error_ae,
            "duracion_min": 18,
        })

    if not en_marcha:
        panel = {"nivel": "informativo", "color": "gris", "titulo": "Planta detenida",
                 "accion": "Los modelos se aplican con el molino en marcha.", "origen": None, "desde": None}
    elif alarmas_activas:
        a0 = alarmas_activas[0]
        panel = {"nivel": "alarma", "color": "morado" if esc == "cavitacion" else "rojo",
                 "titulo": a0["mensaje"], "accion": a0["accion"],
                 "origen": a0["origen_texto"], "desde": a0["inicio"]}
    else:
        panel = {"nivel": "normal", "color": "verde", "titulo": "Operación normal",
                 "accion": "Todas las variables dentro de su banda normal y sin anomalías.",
                 "origen": "diagnóstico y vigilancia", "desde": None}

    diagnostico = {
        "ts": ts.isoformat(),
        "falla": esc_obj["falla"] if esc_obj else None,
        "titulo": esc_obj["titulo"] if esc_obj else "Normal",
        "accion": esc_obj["accion"] if esc_obj else None,
        "prioridad": "alta" if esc_obj else None,
        "probabilidad_anomalia": 0.94 if esc_obj else 0.03,
        "confirmado_por_autoencoder": bool(esc_obj),
    }
    vigilancia = {
        "ts": ts.isoformat(),
        "error": error_ae,
        "umbral": umbral_ae,
        "alerta": error_ae > umbral_ae,
        "indice_salud": 78.5 if esc_obj else 96.4,
        "sensores": [{"tag": t, "porcentaje": round(100.0 / max(1, len(senalados_ae)), 0)} for t in senalados_ae],
    }
    riesgo = [
        {"falla": "Filtro_Obstruido", "titulo": "Filtro obstruido", "riesgo_en": "24h" if esc == "filtro" else "15d"},
        {"falla": "Sobrecarga_Motor_Por_Asfalto_Frio", "titulo": "Sobrecarga por asfalto frío", "riesgo_en": "24h" if esc == "caldera" else None},
        {"falla": "Advertencia_Radar_Sucio_Betun", "titulo": "Radar sucio", "riesgo_en": "5d" if esc == "radar" else None},
        {"falla": "Cortocircuito_Transmisor_Caudal_Sol", "titulo": "Cortocircuito", "riesgo_en": "24h" if esc == "cortocircuito" else None},
        {"falla": "Falla_Electrica_PT100_Betun", "titulo": "Pt100", "riesgo_en": None},
        {"falla": "Ensuciamiento_Intercambiador", "titulo": "Intercambiador", "riesgo_en": None},
        {"falla": "Desgaste_Rodamientos_Molino", "titulo": "Rodamientos", "riesgo_en": "5d" if esc == "rodamientos" else None},
    ]
    indicadores = {
        "desde": (ts - datetime.timedelta(hours=6)).isoformat(),
        "produccion_t": 54.8,
        "relacion_betun_pct": 63.4,
        "relacion_objetivo": (60.0, 68.0),
        "relacion_fuera": False,
        "marcha_sin_anomalia_pct": 89.2 if esc_obj else 99.1,
        "horas_marcha": 6.4,
        "energia_kwh": 342.0,
    }
    texto_est = {"produccion": "En producción", "limpieza": "Limpieza de línea", "detenida": "Planta detenida"}.get(estado, estado)
    return {
        "ts": ts.isoformat(),
        "fuente": "simulado",
        "estado": estado,
        "estado_texto": texto_est,
        "tipo_asfalto": tipo_asfalto,
        "en_marcha": en_marcha,
        "panel": panel,
        "sensores": sensores_out,
        "diagnostico": diagnostico,
        "vigilancia": vigilancia,
        "alarmas_activas": alarmas_activas,
        "riesgo": riesgo,
        "indicadores": indicadores,
        "modelos_aplican": en_marcha,
    }


PUNTOS_MANTENIMIENTO_DEMO: List[Dict[str, Any]] = [
    {"clave": "filtro", "equipo": "F-101 filtro de línea", "componente": "F-101", "falla": "Filtro_Obstruido",
     "correctivas_base": 2, "preventivas_base": 5, "mtbf_base": 18.0, "offset_dias": 8.4, "riesgo_15d": True},
    {"clave": "caldera", "equipo": "TK-101 caldera / calefactor de betún", "componente": "TK-101", "falla": "Sobrecarga_Motor_Por_Asfalto_Frio",
     "correctivas_base": 1, "preventivas_base": 4, "mtbf_base": 32.0, "offset_dias": 14.2, "riesgo_15d": False},
    {"clave": "radar", "equipo": "TK-101 radar de nivel", "componente": "TK-101", "falla": "Advertencia_Radar_Sucio_Betun",
     "correctivas_base": 1, "preventivas_base": 3, "mtbf_base": 28.0, "offset_dias": 21.0, "riesgo_15d": False},
    {"clave": "intercambiador", "equipo": "E-301 intercambiador de calor", "componente": "E-301", "falla": "Ensuciamiento_Intercambiador",
     "correctivas_base": 1, "preventivas_base": 3, "mtbf_base": 45.0, "offset_dias": 26.0, "riesgo_15d": False},
    {"clave": "caudalimetro", "equipo": "FT-201 caudalímetro solución", "componente": "FT-201", "falla": "Cortocircuito_Transmisor_Caudal_Sol",
     "correctivas_base": 1, "preventivas_base": 3, "mtbf_base": 40.0, "offset_dias": 31.0, "riesgo_15d": False},
    {"clave": "pt100", "equipo": "TT-101 Pt100 betún", "componente": "TT-101", "falla": "Falla_Electrica_PT100_Betun",
     "correctivas_base": 1, "preventivas_base": 3, "mtbf_base": 50.0, "offset_dias": 35.0, "riesgo_15d": False},
    {"clave": "rodamientos", "equipo": "MC-01 rodamientos del molino", "componente": "MC-01", "falla": "Desgaste_Rodamientos_Molino",
     "correctivas_base": 0, "preventivas_base": 2, "mtbf_base": 60.0, "offset_dias": 42.5, "riesgo_15d": False},
]

MANTENIMIENTOS_REGISTRADOS_DEMO: List[Dict[str, Any]] = []


def _dias_desde_intervencion_demo(ts: datetime.datetime, codigo_falla: str, base_dias: float) -> float:
    ultima = ts - datetime.timedelta(days=base_dias)
    for m in MANTENIMIENTOS_REGISTRADOS_DEMO:
        if codigo_falla in (m.get("fallas") or []):
            try:
                f_ini = datetime.datetime.fromisoformat(str(m["fecha_inicio"]).replace("Z", "+00:00"))
                if f_ini.tzinfo is None:
                    f_ini = f_ini.replace(tzinfo=datetime.timezone.utc)
                if f_ini > ultima:
                    ultima = f_ini
            except Exception:
                pass
    return max(0.0, round((ts - ultima).total_seconds() / 86400.0, 1))


def obtener_prediccion_pantalla_demo() -> Dict[str, Any]:
    ts = _avanzar_reloj_demo()
    esc = SIM_ESTADO["escenario"]
    fallas = [
        {
            "falla": "Filtro_Obstruido", "titulo": "Filtro obstruido", "componente": "F-101",
            "metodo": "LightGBM", "emitida": ts.isoformat(),
            "dias_desde_intervencion": _dias_desde_intervencion_demo(ts, "Filtro_Obstruido", 8.4), "frecuente": True,
            "accion": "Limpiar canastillo del filtro F-101.",
            "alto_en": ["24h", "5d", "15d"] if esc == "filtro" else ["15d"],
            "horizontes": {
                "24h": {"probabilidad": 0.88 if esc == "filtro" else 0.14, "umbral": 0.45, "alerta": esc == "filtro", "dias_estimados": None},
                "5d": {"probabilidad": 0.92 if esc == "filtro" else 0.31, "umbral": 0.45, "alerta": esc == "filtro", "dias_estimados": None},
                "15d": {"probabilidad": 0.95 if esc == "filtro" else 0.56, "umbral": 0.45, "alerta": True, "dias_estimados": None},
            },
        },
        {
            "falla": "Sobrecarga_Motor_Por_Asfalto_Frio", "titulo": "Sobrecarga por asfalto frío", "componente": "TK-101",
            "metodo": "LightGBM", "emitida": ts.isoformat(),
            "dias_desde_intervencion": _dias_desde_intervencion_demo(ts, "Sobrecarga_Motor_Por_Asfalto_Frio", 14.2), "frecuente": True,
            "accion": "Verificar quemador de caldera y serpentines de TK-101.",
            "alto_en": ["24h", "5d"] if esc == "caldera" else [],
            "horizontes": {
                "24h": {"probabilidad": 0.84 if esc == "caldera" else 0.08, "umbral": 0.42, "alerta": esc == "caldera", "dias_estimados": None},
                "5d": {"probabilidad": 0.89 if esc == "caldera" else 0.15, "umbral": 0.42, "alerta": esc == "caldera", "dias_estimados": None},
                "15d": {"probabilidad": 0.22, "umbral": 0.42, "alerta": False, "dias_estimados": None},
            },
        },
        {
            "falla": "Advertencia_Radar_Sucio_Betun", "titulo": "Radar de betún sucio", "componente": "TK-101",
            "metodo": "LightGBM", "emitida": ts.isoformat(),
            "dias_desde_intervencion": _dias_desde_intervencion_demo(ts, "Advertencia_Radar_Sucio_Betun", 21.0), "frecuente": True,
            "accion": "Programar limpieza de antena radar TK-101.",
            "alto_en": ["5d", "15d"] if esc == "radar" else [],
            "horizontes": {
                "24h": {"probabilidad": 0.19, "umbral": 0.40, "alerta": False, "dias_estimados": None},
                "5d": {"probabilidad": 0.64 if esc == "radar" else 0.21, "umbral": 0.40, "alerta": esc == "radar", "dias_estimados": None},
                "15d": {"probabilidad": 0.78 if esc == "radar" else 0.29, "umbral": 0.40, "alerta": esc == "radar", "dias_estimados": None},
            },
        },
        {
            "falla": "Desgaste_Rodamientos_Molino", "titulo": "Desgaste de rodamientos", "componente": "MC-01",
            "metodo": "Tendencia lineal (7d)", "emitida": ts.isoformat(),
            "dias_desde_intervencion": _dias_desde_intervencion_demo(ts, "Desgaste_Rodamientos_Molino", 42.5), "frecuente": False,
            "accion": "Programar cambio preventivo de rodamientos en parada semanal.",
            "alto_en": ["5d"] if esc == "rodamientos" else [],
            "horizontes": {
                "24h": {"probabilidad": None, "umbral": None, "alerta": False, "dias_estimados": 4.2 if esc == "rodamientos" else 28.0},
                "5d": {"probabilidad": None, "umbral": None, "alerta": esc == "rodamientos", "dias_estimados": 4.2 if esc == "rodamientos" else 28.0},
                "15d": {"probabilidad": None, "umbral": None, "alerta": esc == "rodamientos", "dias_estimados": 4.2 if esc == "rodamientos" else 28.0},
            },
        },
    ]
    return {"ts": ts.isoformat(), "emitida": ts.isoformat(), "fallas": fallas}


def obtener_evolucion_demo(horizonte: str = "5d", dias: int = 7) -> Dict[str, Any]:
    ts = _avanzar_reloj_demo()
    puntos_f, puntos_s, puntos_r = [], [], []
    for i in range(28, -1, -1):
        t_i = (ts - datetime.timedelta(hours=i * 6)).isoformat()
        progreso = (28 - i) / 28.0
        puntos_f.append({"t": t_i, "probabilidad": round(0.18 + 0.68 * (progreso ** 1.6), 3)})
        puntos_s.append({"t": t_i, "probabilidad": round(0.09 + 0.08 * _math.sin(i * 0.4), 3)})
        puntos_r.append({"t": t_i, "probabilidad": round(0.14 + 0.12 * progreso, 3)})
    return {
        "horizonte": horizonte,
        "mensaje": None,
        "series": [
            {"falla": "Filtro_Obstruido", "titulo": "Filtro", "umbral": 0.45, "puntos": puntos_f},
            {"falla": "Sobrecarga_Motor_Por_Asfalto_Frio", "titulo": "Sobrecarga", "umbral": 0.42, "puntos": puntos_s},
            {"falla": "Advertencia_Radar_Sucio_Betun", "titulo": "Radar sucio", "umbral": 0.40, "puntos": puntos_r},
        ],
    }


def obtener_alarmas_pantalla_demo() -> Dict[str, Any]:
    p = obtener_proceso_demo()
    ts = datetime.datetime.fromisoformat(p["ts"])
    historial = list(p["alarmas_activas"]) + [
        {
            "id": 99,
            "inicio": (ts - datetime.timedelta(days=1, hours=4)).isoformat(),
            "fin": (ts - datetime.timedelta(days=1, hours=3, minutes=15)).isoformat(),
            "activa": False,
            "mensaje": "Sobrecarga del motor por asfalto frío",
            "prioridad": "alta",
            "origen": "modelo",
            "origen_texto": "modelo de diagnóstico LightGBM",
            "falla": "Sobrecarga_Motor_Por_Asfalto_Frio",
            "accion": "Revisar caldera y calefacción de TK-101.",
            "duracion_min": 45,
        },
        {
            "id": 98,
            "inicio": (ts - datetime.timedelta(days=3, hours=2)).isoformat(),
            "fin": (ts - datetime.timedelta(days=3, hours=1, minutes=30)).isoformat(),
            "activa": False,
            "mensaje": "Radar de betún sucio",
            "prioridad": "media",
            "origen": "regla fija",
            "origen_texto": "regla fija",
            "falla": "Advertencia_Radar_Sucio_Betun",
            "accion": "Programar limpieza de la antena del radar.",
            "duracion_min": 30,
        },
    ]
    return {"ts": p["ts"], "activas": p["alarmas_activas"], "historial": historial}


def obtener_salud_demo(dias: int = 45) -> Dict[str, Any]:
    ts = _avanzar_reloj_demo()
    umbral = 0.120
    lista = []
    for i in range(14, -1, -1):
        d = (ts - datetime.timedelta(days=i)).date().isoformat()
        err = round(0.032 + (0.008 * (14 - i)) + (0.045 if i == 0 and SIM_ESTADO["escenario"] else 0.0), 3)
        sobre = err > umbral
        lista.append({
            "dia": d,
            "error_medio": err,
            "minutos_marcha": 420 - (i % 3) * 35,
            "minutos_anomalia": 24 if sobre else 0,
            "sobre_umbral": sobre,
        })
    return {
        "ts": ts.isoformat(),
        "umbral": umbral,
        "dias": lista,
        "dias_sobre_umbral": sum(1 for x in lista if x["sobre_umbral"]),
    }


def registrar_mantenimiento_demo(
    *,
    componente_nombre: str,
    codigo_componente: str | None,
    tipo: str,
    fecha_inicio: datetime.datetime,
    fecha_fin: datetime.datetime | None,
    fallas: List[str],
    descripcion: str | None,
    registrado_por: str,
    fuente: str = "simulado",
) -> Dict[str, Any]:
    if fecha_inicio.tzinfo is None:
        fecha_inicio = fecha_inicio.replace(tzinfo=datetime.timezone.utc)
    if fecha_fin is not None and fecha_fin.tzinfo is None:
        fecha_fin = fecha_fin.replace(tzinfo=datetime.timezone.utc)
    titulos_falla = {f["codigo"]: f["titulo"] for f in TIPOS_FALLA}
    nuevo_id = 100 + len(MANTENIMIENTOS_REGISTRADOS_DEMO) + 1
    registro = {
        "id": nuevo_id,
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat() if fecha_fin else None,
        "componente": componente_nombre,
        "codigo_componente": codigo_componente,
        "tipo": tipo,
        "descripcion": descripcion or "",
        "fallas": list(fallas),
        "fallas_atendidas": [titulos_falla.get(c, c) for c in fallas],
        "origen_registro": "dashboard",
        "registrado_por": registrado_por,
        "fuente": fuente,
    }
    MANTENIMIENTOS_REGISTRADOS_DEMO.insert(0, registro)
    return registro


def obtener_mantenimiento_demo() -> Dict[str, Any]:
    ts = _avanzar_reloj_demo()
    equipos = []
    for p in PUNTOS_MANTENIMIENTO_DEMO:
        corr_extra = sum(
            1 for m in MANTENIMIENTOS_REGISTRADOS_DEMO
            if p["falla"] in (m.get("fallas") or []) and m["tipo"] == "correctivo"
        )
        prev_extra = sum(
            1 for m in MANTENIMIENTOS_REGISTRADOS_DEMO
            if p["falla"] in (m.get("fallas") or []) and m["tipo"] in ("preventivo", "predictivo")
        )
        ultima_dt = ts - datetime.timedelta(days=p["offset_dias"])
        for m in MANTENIMIENTOS_REGISTRADOS_DEMO:
            if p["falla"] in (m.get("fallas") or []):
                try:
                    f_ini = datetime.datetime.fromisoformat(str(m["fecha_inicio"]).replace("Z", "+00:00"))
                    if f_ini.tzinfo is None:
                        f_ini = f_ini.replace(tzinfo=datetime.timezone.utc)
                    if f_ini > ultima_dt:
                        ultima_dt = f_ini
                except Exception:
                    pass
        dias_desde = max(0.0, round((ts - ultima_dt).total_seconds() / 86400.0, 1))
        equipos.append({
            "clave": p["clave"],
            "equipo": p["equipo"],
            "componente": p["componente"],
            "falla": p["falla"],
            "correctivas": p["correctivas_base"] + corr_extra,
            "preventivas": p["preventivas_base"] + prev_extra,
            "mtbf_dias": p["mtbf_base"],
            "ultima_intervencion": ultima_dt.isoformat(),
            "dias_desde": dias_desde,
            "riesgo_15d": False if (corr_extra + prev_extra) > 0 and dias_desde < 2.0 else p["riesgo_15d"],
        })

    bitacora_base = [
        {"id": 3, "fecha_inicio": (ts - datetime.timedelta(days=8)).isoformat(), "fecha_fin": None,
         "componente": "F-101 filtro de línea", "tipo": "preventivo",
         "descripcion": "Limpieza programada de malla y drenaje de sedimentos asfálticos.",
         "origen_registro": "bitacora", "registrado_por": None, "fallas_atendidas": ["Filtro obstruido"]},
        {"id": 2, "fecha_inicio": (ts - datetime.timedelta(days=14)).isoformat(), "fecha_fin": None,
         "componente": "TK-101 caldera", "tipo": "preventivo",
         "descripcion": "Ajuste de control térmico y purga de circuito de aceite térmico.",
         "origen_registro": "bitacora", "registrado_por": None, "fallas_atendidas": ["Sobrecarga del motor por asfalto frío"]},
        {"id": 1, "fecha_inicio": (ts - datetime.timedelta(days=21)).isoformat(), "fecha_fin": None,
         "componente": "TK-101 radar", "tipo": "correctivo",
         "descripcion": "Remoción de costra de betún en cono emisor del radar.",
         "origen_registro": "bitacora", "registrado_por": None, "fallas_atendidas": ["Radar de betún sucio"]},
    ]
    bitacora = sorted(
        list(MANTENIMIENTOS_REGISTRADOS_DEMO) + bitacora_base,
        key=lambda x: str(x.get("fecha_inicio") or ""),
        reverse=True,
    )
    total_base = 18
    preventivas_base = 14
    total_extra = len(MANTENIMIENTOS_REGISTRADOS_DEMO)
    prev_extra_total = sum(1 for m in MANTENIMIENTOS_REGISTRADOS_DEMO if m["tipo"] in ("preventivo", "predictivo"))
    total_int = total_base + total_extra
    pct_plan = round(100.0 * (preventivas_base + prev_extra_total) / total_int, 1) if total_int else None
    return {
        "ts": ts.isoformat(),
        "equipos": equipos,
        "pct_planificado": pct_plan,
        "total_intervenciones": total_int,
        "bitacora": bitacora,
        "nota": "Bitácora de demostración en memoria (incluye intervenciones registradas en esta sesión).",
    }

