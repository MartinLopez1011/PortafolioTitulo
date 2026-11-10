"""Fixtures de la Lambda de inferencia. Se ejecutan dentro de la imagen Docker
(public.ecr.aws/lambda/python:3.12), que ya contiene TensorFlow, LightGBM y los artefactos."""
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
# Credenciales ficticias: los clientes boto3 se crean al importar pero se reemplazan por mocks.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    from app.inference_engine import MolinoInferenceEngine
    return MolinoInferenceEngine()


@pytest.fixture
def payload_plano():
    return json.loads((RAIZ / "app" / "test_payload_flat.json").read_text(encoding="utf-8"))


@pytest.fixture
def payload_anidado():
    return json.loads((RAIZ / "app" / "test_payload.json").read_text(encoding="utf-8"))
