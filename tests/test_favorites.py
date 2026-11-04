from tests.conftest import register_and_login

FAV = {"title": "Phone", "link": "https://shop.example/p/1", "price": "1.299,50", "source": "Shop", "thumbnail": None}


def test_add_is_idempotent_and_parses_price(client):
    headers = register_and_login(client)
    r1 = client.post("/api/v1/favorites/", json=FAV, headers=headers)
    assert r1.status_code == 201
    assert r1.json()["price"] == 1299.5
    assert r1.json()["currency"] == "TRY"
    assert r1.json()["added_at"]
    r2 = client.post("/api/v1/favorites/", json=FAV, headers=headers)
    assert r2.status_code == 200 and r2.json()["id"] == r1.json()["id"]
    assert len(client.get("/api/v1/favorites/", headers=headers).json()) == 1


def test_delete_by_link(client):
    headers = register_and_login(client)
    client.post("/api/v1/favorites/", json=FAV, headers=headers)
    r = client.delete("/api/v1/favorites/by-link", params={"link": FAV["link"]}, headers=headers)
    assert r.status_code == 204
    assert client.get("/api/v1/favorites/", headers=headers).json() == []


def test_cannot_delete_others_favorite(client):
    a = register_and_login(client, email="a@example.com")
    b = register_and_login(client, email="b@example.com")
    fid = client.post("/api/v1/favorites/", json=FAV, headers=a).json()["id"]
    assert client.delete(f"/api/v1/favorites/{fid}", headers=b).status_code == 404
