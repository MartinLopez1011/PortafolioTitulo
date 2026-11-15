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


def test_mantenimiento_requiere_autenticacion(client):
    r = client.post(
        "/api/mantenimientos",
        json={
            "clave_equipo": "filtro",
            "tipo": "preventivo",
            "fecha_inicio": "2026-04-28T07:50:00",
            "descripcion": "Limpieza de malla del filtro de succión.",
        },
    )
    assert r.status_code == 401


def test_operador_y_admin_pueden_registrar_mantenimiento_y_actualizar_pantalla(client, token_operador, token_admin):
    cab_op = {"Authorization": f"Bearer {token_operador}"}
    cab_adm = {"Authorization": f"Bearer {token_admin}"}

    antes = client.get("/api/mantenimiento/pantalla", headers=cab_op).json()
    total_antes = antes["total_intervenciones"]
    filtro_antes = next(e for e in antes["equipos"] if e["clave"] == "filtro")

    r_op = client.post(
        "/api/mantenimientos",
        headers=cab_op,
        json={
            "clave_equipo": "filtro",
            "tipo": "preventivo",
            "fecha_inicio": "2026-04-28T07:50:00",
            "descripcion": "Limpieza programada de malla de succión.",
            "fuente": "simulado",
        },
    )
    assert r_op.status_code == 201
    reg_op = r_op.json()["mantenimiento"]
    assert reg_op["componente"] == "F-101 filtro de línea"
    assert reg_op["codigo_componente"] == "F-101"
    assert reg_op["fallas"] == ["Filtro_Obstruido"]
    assert reg_op["origen_registro"] == "dashboard"

    r_adm = client.post(
        "/api/mantenimientos",
        headers=cab_adm,
        json={
            "clave_equipo": "rodamientos",
            "tipo": "correctivo",
            "fecha_inicio": "2026-04-28T07:52:00",
            "fecha_fin": "2026-04-28T08:30:00",
            "descripcion": "Reemplazo de rodamientos del molino MC-01.",
            "fuente": "simulado",
        },
    )
    assert r_adm.status_code == 201

    despues = client.get("/api/mantenimiento/pantalla", headers=cab_op).json()
    assert despues["total_intervenciones"] == total_antes + 2
    filtro_despues = next(e for e in despues["equipos"] if e["clave"] == "filtro")
    assert filtro_despues["preventivas"] == filtro_antes["preventivas"] + 1
    assert any(b["descripcion"] == "Limpieza programada de malla de succión." for b in despues["bitacora"])


def test_mantenimiento_valida_fechas_y_equipo(client, token_operador):
    cab_op = {"Authorization": f"Bearer {token_operador}"}
    r_fechas = client.post(
        "/api/mantenimientos",
        headers=cab_op,
        json={
            "clave_equipo": "filtro",
            "tipo": "preventivo",
            "fecha_inicio": "2026-04-28T08:00:00",
            "fecha_fin": "2026-04-28T07:00:00",
            "descripcion": "Fechas invertidas.",
        },
    )
    assert r_fechas.status_code == 422

    r_eq = client.post(
        "/api/mantenimientos",
        headers=cab_op,
        json={
            "clave_equipo": "equipo_inexistente",
            "tipo": "preventivo",
            "fecha_inicio": "2026-04-28T08:00:00",
            "descripcion": "Equipo desconocido.",
        },
    )
    assert r_eq.status_code == 422

