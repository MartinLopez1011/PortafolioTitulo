"""Endpoint de salud (usado por Docker HEALTHCHECK y el smoke test del CD) y dashboard estático."""


def test_salud_modo_demo(client):
    r = client.get("/api/salud")
    assert r.status_code == 200
    datos = r.json()
    assert datos["api"] == "ok"
    assert datos["base_de_datos"] == "modo_demostracion"
    assert "hora_bd" in datos


def test_dashboard_index_se_sirve(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_login_html_se_sirve(client):
    r = client.get("/login.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_docs_openapi_disponible(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/salud" in r.json()["paths"]
