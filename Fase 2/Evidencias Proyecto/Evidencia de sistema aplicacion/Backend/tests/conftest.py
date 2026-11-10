"""Configuración común: la API se prueba en MODO_DEMO (sin base de datos ni AWS)."""
import os
import sys
from pathlib import Path

# Variables definidas ANTES de importar app.config (que lee el entorno al importarse).
os.environ["MODO_DEMO"] = "1"
os.environ["DEMO_CLAVE"] = "ClaveDemo2026"
os.environ["JWT_SECRET"] = "x" * 48
os.environ.setdefault("JWT_MINUTOS", "60")
os.environ.pop("DATABASE_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DEMO_CLAVE = os.environ["DEMO_CLAVE"]


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app) as c:   # el "with" ejecuta el ciclo de vida (config.validar, db.abrir)
        yield c


@pytest.fixture
def token_admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@demo.qla.cl", "clave": DEMO_CLAVE})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture
def token_operador(client):
    r = client.post("/api/auth/login", json={"email": "operador@demo.qla.cl", "clave": DEMO_CLAVE})
    assert r.status_code == 200
    return r.json()["access_token"]
