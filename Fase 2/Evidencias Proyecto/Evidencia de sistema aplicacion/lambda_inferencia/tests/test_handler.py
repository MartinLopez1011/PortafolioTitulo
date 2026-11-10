"""Handler Lambda con los servicios AWS (DynamoDB, IoT, S3) reemplazados por mocks."""
import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def lf(monkeypatch):
    from app import lambda_function as lf
    monkeypatch.setattr(lf, "table", MagicMock())
    monkeypatch.setattr(lf, "iot_client", MagicMock())
    s3 = MagicMock()
    s3.get_object.side_effect = Exception("sin S3 en tests")
    monkeypatch.setattr(lf, "s3_client", s3)
    monkeypatch.setattr(lf, "actualizar_ventana_168h", lambda lectura: __import__("pandas").DataFrame([lectura]))
    return lf


def test_handler_payload_plano(lf, payload_plano):
    r = lf.lambda_handler(payload_plano, None)
    assert r["statusCode"] == 200
    lf.table.put_item.assert_called_once()
    assert lf.iot_client.publish.called


def test_handler_body_string_api_gateway(lf, payload_plano):
    r = lf.lambda_handler({"body": json.dumps(payload_plano)}, None)
    assert r["statusCode"] == 200


def test_handler_motor_no_disponible(lf, monkeypatch, payload_plano):
    monkeypatch.setattr(lf, "get_engine", lambda: None)
    r = lf.lambda_handler(payload_plano, None)
    assert r["statusCode"] == 500


def test_convert_floats_to_decimal(lf):
    from decimal import Decimal
    out = lf._convert_floats_to_decimal({"a": 1.5, "b": [2.25]})
    assert out == {"a": Decimal("1.5"), "b": [Decimal("2.25")]}
