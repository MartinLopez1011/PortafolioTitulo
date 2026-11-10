"""Validación de configuración al arrancar."""
import pytest

from app import config


def test_validar_ok_en_modo_demo():
    config.validar()


def test_validar_jwt_corto(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "corto")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        config.validar()


def test_validar_sin_db_ni_demo(monkeypatch):
    monkeypatch.setattr(config, "MODO_DEMO", False)
    monkeypatch.setattr(config, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        config.validar()
