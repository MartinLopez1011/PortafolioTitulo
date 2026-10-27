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
