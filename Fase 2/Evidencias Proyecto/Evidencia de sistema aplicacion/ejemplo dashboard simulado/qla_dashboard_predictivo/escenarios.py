"""
Escenarios de falla para simular en el dashboard.

Cada escenario parte de las lecturas normales y aplica una lista de efectos:
    - "fijar":        el sensor pasa a leer exactamente `valor`
    - "sumar":        se suma `valor` a la lectura normal
    - "multiplicar":  la lectura normal se multiplica por `valor`

La evolución puede ser "inmediata" (la falla aparece de golpe) o "gradual"
(se desarrolla a lo largo de `minutos`; en la simulación en vivo cada paso es un minuto).

Los escenarios personalizados que crea el usuario se guardan en escenarios_personalizados.json.
"""
import json
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ARCHIVO = Path(__file__).parent / "escenarios_personalizados.json"
_lock = threading.Lock()


class Efecto(BaseModel):
    sensor: str
    operacion: Literal["fijar", "sumar", "multiplicar"]
    valor: float


class Escenario(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    descripcion: str = Field(default="", max_length=400)
    evolucion: Literal["inmediata", "gradual"] = "inmediata"
    minutos: int = Field(default=15, ge=1, le=20160)
    efectos: list[Efecto] = Field(min_length=1)


def _e(sensor, operacion, valor):
    return {"sensor": sensor, "operacion": operacion, "valor": valor}


# ---------------------------------------------------------------------------
# Escenarios sobre la operación real. Los efectos se suman a los datos reproducidos;
# las señales del motor, bomba y filtro solo cambian con el molino en marcha.
# Los escenarios graduales permiten ver cómo el modelo predictivo anticipa la falla.
# ---------------------------------------------------------------------------
CONOCIDAS = [
    {"nombre": "Caldera perdiendo potencia",
     "descripcion": "El betún se enfría de a poco; al bajar de ~125 °C el motor entra en sobrecarga.",
     "evolucion": "gradual", "minutos": 4 * 1440,
     "efectos": [_e("TEM_son_betum_in", "sumar", -22), _e("AMP_vfd_motor_molino", "sumar", 22),
                 _e("TOR_vfd_motor_molino", "sumar", 22), _e("VIB_vel_motor_molino", "sumar", 1.0)]},
    {"nombre": "Filtro obstruyéndose",
     "descripcion": "El filtro acumula sólidos: sube la presión diferencial y cae el caudal de la bomba.",
     "evolucion": "gradual", "minutos": 5 * 1440,
     "efectos": [_e("PRE_dif_filtro_bar", "sumar", 0.9), _e("CAU_bomba_lpm", "sumar", -22)]},
    {"nombre": "Radar ensuciándose",
     "descripcion": "Costra de asfalto en la antena del radar de TK-101: el eco se debilita.",
     "evolucion": "gradual", "minutos": 7 * 1440,
     "efectos": [_e("AMP_eco_betum_dep", "sumar", -42)]},
    {"nombre": "Humedad en caudalímetro",
     "descripcion": "Corriente de fuga creciente en el lazo de FT-201 antes del cortocircuito.",
     "evolucion": "gradual", "minutos": 5 * 1440,
     "efectos": [_e("AMP_cau_solucion_in", "sumar", 1.6)]},
    {"nombre": "Cortocircuito caudalímetro",
     "descripcion": "El lazo de FT-201 se satura sobre 22 mA.",
     "evolucion": "inmediata", "minutos": 1,
     "efectos": [_e("AMP_cau_solucion_in", "fijar", 22.51)]},
    {"nombre": "Borneras Pt100 corroídas",
     "descripcion": "Cae el voltaje de alimentación de la Pt100 del betún.",
     "evolucion": "gradual", "minutos": 6 * 1440,
     "efectos": [_e("VOLT_son_betum_in", "sumar", -1.6)]},
    {"nombre": "Pt100 sin alimentación",
     "descripcion": "Pérdida total de los 24 V: temperatura, resistencia y lazo en cero.",
     "evolucion": "inmediata", "minutos": 1,
     "efectos": [_e("TEM_son_betum_in", "fijar", 0), _e("RES_son_betum_in", "fijar", 0),
                 _e("VOLT_son_betum_in", "fijar", 0), _e("AMP_son_betum_in", "fijar", 0)]},
    {"nombre": "Intercambiador ensuciándose",
     "descripcion": "Depósitos en E-301: sube la presión en producción plastomérica.",
     "evolucion": "gradual", "minutos": 6 * 1440,
     "efectos": [_e("PRE_intercambiador_bar", "sumar", 1.3), _e("TEM_son_emulsion_out", "sumar", 8)]},
    {"nombre": "Rodamientos desgastándose",
     "descripcion": "Desgaste mecánico: la vibración del molino sube durante días.",
     "evolucion": "gradual", "minutos": 10 * 1440,
     "efectos": [_e("VIB_vel_motor_molino", "sumar", 3.2), _e("AMP_vfd_motor_molino", "sumar", 4)]},
]

# Fallas que ningún modelo vio: solo el autoencoder y las reglas pueden detectarlas
NUEVAS = [
    {"nombre": "Bomba cavitando",
     "descripcion": "Aire o vapor en la succión: el caudal cae y oscila, la frecuencia del Coriolis de emulsión sube.",
     "evolucion": "gradual", "minutos": 360,
     "efectos": [_e("CAU_bomba_lpm", "multiplicar", 0.8), _e("FRE_cau_emulsion_out", "sumar", 18)]},
    {"nombre": "Sello mecánico con fuga",
     "descripcion": "Roce en el sello del molino: sube la temperatura de salida y algo la vibración.",
     "evolucion": "gradual", "minutos": 1440,
     "efectos": [_e("TEM_emulsion_molino_out", "sumar", 12), _e("VIB_vel_motor_molino", "sumar", 0.8)]},
    {"nombre": "Solución fría",
     "descripcion": "Falla del calefactor de la solución jabonosa: baja a 22 °C.",
     "evolucion": "gradual", "minutos": 720,
     "efectos": [_e("TEM_son_solucion_in", "sumar", -14)]},
    {"nombre": "Variador inestable",
     "descripcion": "El variador del molino oscila: baja la velocidad y la frecuencia.",
     "evolucion": "inmediata", "minutos": 1,
     "efectos": [_e("RPM_motor_molino", "multiplicar", 0.85), _e("FRE_vfd_motor_molino", "multiplicar", 0.85)]},
]


def predefinidos():
    return ([{**e, "categoria": "conocida", "editable": False} for e in CONOCIDAS] +
            [{**e, "categoria": "nueva", "editable": False} for e in NUEVAS])


def nombres_reservados():
    return {e["nombre"].lower() for e in CONOCIDAS + NUEVAS} | {"normal"}


def cargar_personalizados():
    if not ARCHIVO.exists():
        return []
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def guardar_personalizado(esc: Escenario):
    with _lock:
        lista = [e for e in cargar_personalizados() if e["nombre"].lower() != esc.nombre.lower()]
        lista.append(esc.model_dump())
        ARCHIVO.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def eliminar_personalizado(nombre: str) -> bool:
    with _lock:
        lista = cargar_personalizados()
        nueva = [e for e in lista if e["nombre"].lower() != nombre.lower()]
        if len(nueva) == len(lista):
            return False
        ARCHIVO.write_text(json.dumps(nueva, ensure_ascii=False, indent=2), encoding="utf-8")
        return True


def todos():
    return predefinidos() + [{**e, "categoria": "personalizada", "editable": True}
                             for e in cargar_personalizados()]
