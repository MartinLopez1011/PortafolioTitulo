import json
import time
import random
from datetime import datetime, timezone

# Valores base de operación normal en Producción | Convencional
VALORES_BASE_29_SENSORES = {
    "TEM_son_betum_in": 138.5,
    "RES_son_betum_in": 153.2,
    "VOLT_son_betum_in": 23.4,
    "AMP_son_betum_in": 11.8,
    "AMP_cau_betum_in": 12.1,
    "FRE_cau_betum_in": 48.0,
    "AMP_eco_betum_dep": 36.4,
    "EST_niv_betum_dep": 0.72,
    "TEM_son_solucion_in": 42.1,
    "RES_son_solucion_in": 116.5,
    "AMP_son_solucion_in": 9.8,
    "AMP_cau_solucion_in": 12.2,
    "FRE_cau_solucion_in": 49.5,
    "AMP_eco_solucion_dep": 70.3,
    "TEM_son_emulsion_out": 88.4,
    "RES_son_emulsion_out": 134.1,
    "AMP_cau_emulsion_out": 14.2,
    "FRE_cau_emulsion_out": 50.0,
    "AMP_eco_emulsion_dep": 59.8,
    "RPM_motor_molino": 2950.0,
    "FRE_vfd_motor_molino": 49.8,
    "AMP_vfd_motor_molino": 98.5,
    "TOR_vfd_motor_molino": 72.4,
    "VIB_vel_motor_molino": 2.35,
    "AMP_vib_motor_molino": 3.1,
    "CAU_bomba_lpm": 185.0,
    "PRE_dif_filtro_bar": 0.48,
    "TEM_emulsion_molino_out": 89.2,
    "PRE_intercambiador_bar": 1.15,
}

def generar_trama_telemetria(modo="normal", estado="Produccion", tipo_asfalto="Convencional") -> dict:
    trama = {
        "device_id": "Gateway_Molino",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ESTADO_operacion": estado,
        "TIPO_asfalto": tipo_asfalto,
    }
    for sensor, valor in VALORES_BASE_29_SENSORES.items():
        ruido = random.gauss(0, abs(valor) * 0.01 + 0.01)
        trama[sensor] = round(valor + ruido, 4)

    # Inyección opcional de fallas para pruebas de integración
    if modo == "asfalto_frio":
        trama["TEM_son_betum_in"] = round(random.uniform(105.0, 115.0), 2)
        trama["AMP_vfd_motor_molino"] = round(random.uniform(135.0, 150.0), 2)
        trama["TOR_vfd_motor_molino"] = round(random.uniform(95.0, 110.0), 2)
    elif modo == "filtro_obstruido":
        trama["PRE_dif_filtro_bar"] = round(random.uniform(1.45, 1.95), 3)
        trama["CAU_bomba_lpm"] = round(random.uniform(110.0, 135.0), 2)
    elif modo == "desgaste_rodamientos":
        trama["VIB_vel_motor_molino"] = round(random.uniform(6.5, 9.2), 3)
        trama["AMP_vib_motor_molino"] = round(random.uniform(7.5, 11.0), 3)

    return trama

if __name__ == "__main__":
    print(json.dumps(generar_trama_telemetria(modo="normal"), indent=2))