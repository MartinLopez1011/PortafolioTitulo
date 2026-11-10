"""Contrato canónico de 31 variables (29 sensores + es_plastomerico + en_limpieza)."""
import math

import pytest

from app.inference_engine import SENSORES_29, MolinoInferenceEngine as E


def test_contrato_tiene_29_sensores():
    assert len(SENSORES_29) == 29
    assert len(set(SENSORES_29)) == 29


def test_normaliza_payload_plano(engine, payload_plano):
    r = engine.Normalizar_Entrada_31(payload_plano)
    for s in SENSORES_29:
        assert isinstance(r[s], float)
    assert r["es_plastomerico"] in (0, 1)
    assert r["en_limpieza"] in (0, 1)
    assert isinstance(r["timestamp"], int)


def test_normaliza_payload_anidado(engine):
    r = engine.Normalizar_Entrada_31({
        "timestamp": 1729000000, "ESTADO_operacion": "Limpieza", "TIPO_asfalto": "plastomérico",
        "lectura_actual": {"TEM_son_betum_in": 150.5},
    })
    assert r["TEM_son_betum_in"] == 150.5
    assert r["ESTADO_operacion"] == "Limpieza" and r["en_limpieza"] == 1
    assert r["TIPO_asfalto"] == "Plastomerico" and r["es_plastomerico"] == 1


@pytest.mark.parametrize("valor", [None, "abc", float("nan"), float("inf")])
def test_valores_invalidos_se_reemplazan_por_cero(engine, valor):
    r = engine.Normalizar_Entrada_31({"TEM_son_betum_in": valor})
    assert r["TEM_son_betum_in"] == 0.0


def test_sensores_faltantes_quedan_en_cero(engine):
    r = engine.Normalizar_Entrada_31({})
    assert all(r[s] == 0.0 for s in SENSORES_29)
    assert r["ESTADO_operacion"] == "Produccion"
    assert r["TIPO_asfalto"] == "Convencional"


@pytest.mark.parametrize("entrada,esperado", [
    (1729000000, 1729000000),
    (1729000000000, 1729000000),
    ("1729000000", 1729000000),
    ("2024-10-15T13:46:40Z", 1729000000),
])
def test_normalizar_timestamp(entrada, esperado):
    assert E._normalizar_timestamp_epoch(entrada) == esperado


def test_timestamp_invalido_usa_ahora():
    assert E._normalizar_timestamp_epoch("no-fecha") > 1_700_000_000
    assert E._normalizar_timestamp_epoch(math.nan) > 1_700_000_000


@pytest.mark.parametrize("estado,tipo,esperado", [
    ("producción", "convencional", ("Produccion", "Convencional")),
    ("DETENIDO", "Plastomerico", ("Detenida", "Plastomerico")),
    ("desconocido", "plasto-x", ("Produccion", "Plastomerico")),
])
def test_normalizar_estado_y_tipo(estado, tipo, esperado):
    assert E._normalizar_estado_y_tipo(estado, tipo, 0, 0) == esperado


def test_preparar_31_features_forma(engine, payload_plano):
    df = engine._preparar_31_features(payload_plano)
    assert df.shape == (1, 31)
    assert str(df.dtypes.iloc[0]) == "float32"
