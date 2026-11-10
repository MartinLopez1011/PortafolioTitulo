"""Carga de artefactos y ejecución de los modelos 1 y 2 en tiempo real."""


def test_artefactos_cargados(engine):
    assert len(engine.features_31) == 31
    assert len(engine.features_80) > 0
    assert engine.umbral_vig > 0


def test_ejecutar_tiempo_real(engine, payload_plano):
    lectura = engine.Normalizar_Entrada_31(payload_plano)
    r = engine.ejecutar_tiempo_real(lectura)
    assert isinstance(r, dict)
    assert "diagnostico" in r
    assert "vigilancia_autoencoder" in r
