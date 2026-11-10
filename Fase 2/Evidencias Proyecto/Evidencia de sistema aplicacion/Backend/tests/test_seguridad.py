"""Pruebas unitarias del módulo de seguridad (bcrypt, JWT, validaciones)."""
import datetime as dt

import jwt
import pytest
from fastapi import HTTPException

from app import config, seguridad


def test_hash_y_verificacion_de_clave():
    h = seguridad.hash_clave("Molino2026")
    assert h != "Molino2026"
    assert seguridad.verificar_clave("Molino2026", h)
    assert not seguridad.verificar_clave("otra", h)


def test_verificar_clave_con_hash_corrupto_no_lanza():
    assert seguridad.verificar_clave("x", "no-es-bcrypt") is False


@pytest.mark.parametrize("clave", ["corta1", "sinnumeros", "12345678", "a1" * 40])
def test_validar_clave_nueva_rechaza(clave):
    with pytest.raises(HTTPException) as e:
        seguridad.validar_clave_nueva(clave)
    assert e.value.status_code == 422


def test_validar_clave_nueva_acepta():
    seguridad.validar_clave_nueva("Asfalto2026")


def test_crear_token_contiene_claims():
    tok = seguridad.crear_token({"id": 7, "rol": "operador", "nivel": 2})
    datos = jwt.decode(tok, config.JWT_SECRET, algorithms=["HS256"])
    assert datos["sub"] == "7"
    assert datos["rol"] == "operador"
    assert datos["nivel"] == 2
    assert datos["exp"] > datos["iat"]


def test_token_valido_y_expirado():
    assert seguridad.token_valido(None) is None
    assert seguridad.token_valido("basura") is None
    ok = seguridad.crear_token({"id": 1, "rol": "administrador", "nivel": 4})
    assert seguridad.token_valido(ok)["sub"] == "1"
    vencido = jwt.encode(
        {"sub": "1", "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)},
        config.JWT_SECRET, algorithm="HS256")
    assert seguridad.token_valido(vencido) is None


def test_token_firmado_con_otra_clave_es_invalido():
    falso = jwt.encode({"sub": "1"}, "y" * 48, algorithm="HS256")
    assert seguridad.token_valido(falso) is None


def test_clave_ingesta(monkeypatch):
    monkeypatch.setattr(config, "CLAVE_INGESTA", "k" * 30)
    assert seguridad.clave_ingesta_valida("k" * 30)
    assert not seguridad.clave_ingesta_valida("k" * 29)
    assert not seguridad.clave_ingesta_valida(None)
    monkeypatch.setattr(config, "CLAVE_INGESTA", "")
    assert not seguridad.clave_ingesta_valida("")


def test_requiere_nivel():
    dep = seguridad.requiere_nivel(seguridad.ADMINISTRADOR)
    assert dep({"nivel": 4})["nivel"] == 4
    with pytest.raises(HTTPException) as e:
        dep({"nivel": 2})
    assert e.value.status_code == 403
