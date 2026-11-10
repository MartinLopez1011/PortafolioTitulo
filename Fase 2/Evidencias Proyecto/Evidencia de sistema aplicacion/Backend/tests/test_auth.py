"""Login, /me y control de acceso por rol en modo demostración."""
from tests.conftest import DEMO_CLAVE


def test_login_correcto_devuelve_token(client):
    r = client.post("/api/auth/login", json={"email": "ADMIN@demo.qla.cl ", "clave": DEMO_CLAVE})
    assert r.status_code == 200
    datos = r.json()
    assert datos["token_type"] == "bearer"
    assert datos["usuario"]["rol"] == "administrador"
    assert "password_hash" not in datos["usuario"]


def test_login_clave_incorrecta(client):
    r = client.post("/api/auth/login", json={"email": "admin@demo.qla.cl", "clave": "mala"})
    assert r.status_code == 401


def test_login_usuario_inexistente(client):
    r = client.post("/api/auth/login", json={"email": "nadie@demo.qla.cl", "clave": DEMO_CLAVE})
    assert r.status_code == 401


def test_login_valida_esquema(client):
    r = client.post("/api/auth/login", json={"email": "a"})
    assert r.status_code == 422


def test_me_sin_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_token_invalido(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer no-es-un-jwt"})
    assert r.status_code == 401


def test_me_con_token(client, token_operador):
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_operador}"})
    assert r.status_code == 200
    assert r.json()["email"] == "operador@demo.qla.cl"


def test_operador_no_puede_listar_usuarios(client, token_operador):
    r = client.get("/api/usuarios", headers={"Authorization": f"Bearer {token_operador}"})
    assert r.status_code == 403
