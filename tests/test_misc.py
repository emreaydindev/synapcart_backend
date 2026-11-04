from app.services.search_service import get_serp_params


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_serp_params_currency():
    assert get_serp_params("x", "en", "TRY")["gl"] == "tr"
    assert get_serp_params("x", "tr", "USD")["gl"] == "us"
    assert get_serp_params("x", "en", "USD")["gl"] == "us"
    assert get_serp_params("x", "de", "EUR")["gl"] == "de"
