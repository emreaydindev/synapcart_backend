from datetime import timedelta

from jose import jwt

from app.core.config import settings
from app.core.database import SessionLocal, utcnow
from app.core.security import hash_reset_token
from app.models.user import User
from tests.conftest import register_and_login


def test_register_validates_password(client):
    r = client.post("/api/v1/auth/register", json={"email": "a@b.com", "password": "short", "name": "A"})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert "8" in r.json()["detail"]


def test_email_is_case_insensitive(client):
    register_and_login(client, email="Mixed@Example.com")
    r = client.post("/api/v1/auth/login", json={"email": "mixed@example.COM", "password": "secret123"})
    assert r.status_code == 200
    r = client.post("/api/v1/auth/register", json={"email": "MIXED@example.com", "password": "secret123", "name": "B"})
    assert r.status_code == 400


def test_login_token_lasts_configured_time_and_has_name(client):
    register_and_login(client)
    r = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "secret123"})
    body = r.json()
    assert body["user_name"] == "Ada"
    payload = jwt.get_unverified_claims(body["access_token"])
    lifetime = payload["exp"] - utcnow().timestamp()
    # utcnow() is naive; compare in minutes with slack.
    expected = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert lifetime > expected - 24 * 3600


def test_wrong_password_is_401(client):
    register_and_login(client)
    r = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "nope12345"})
    assert r.status_code == 401


def test_password_reset_flow_revokes_old_tokens(client, monkeypatch):
    headers = register_and_login(client)
    sent = {}

    async def fake_send(email, token):
        sent["token"] = token

    monkeypatch.setattr("app.api.v1.endpoints.auth.send_reset_email", fake_send)
    r = client.post("/api/v1/auth/forgot-password", json={"email": "user@example.com"})
    assert r.status_code == 200
    raw = sent["token"]

    with SessionLocal() as db:
        user = db.query(User).first()
        assert user.reset_token == hash_reset_token(raw)  # stored hashed

    r = client.post("/api/v1/auth/reset-password", json={"token": raw, "new_password": "newpass123"})
    assert r.status_code == 200

    # Old JWT no longer valid, token single-use
    assert client.get("/api/v1/user/me", headers=headers).status_code == 401
    r = client.post("/api/v1/auth/reset-password", json={"token": raw, "new_password": "other1234"})
    assert r.status_code == 400
    r = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "newpass123"})
    assert r.status_code == 200


def test_forgot_password_smtp_failure_does_not_leak(client, monkeypatch):
    register_and_login(client)

    async def boom(email, token):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.api.v1.endpoints.auth.send_reset_email", boom)
    known = client.post("/api/v1/auth/forgot-password", json={"email": "user@example.com"})
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_expired_reset_token(client):
    register_and_login(client)
    with SessionLocal() as db:
        user = db.query(User).first()
        user.reset_token = hash_reset_token("tok")
        user.reset_token_expires = utcnow() - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/v1/auth/reset-password", json={"token": "tok", "new_password": "newpass123"})
    assert r.status_code == 400


def test_change_password_and_delete_account(client):
    headers = register_and_login(client)
    r = client.post(
        "/api/v1/user/me/password",
        json={"current_password": "wrongpass1", "new_password": "another123"},
        headers=headers,
    )
    assert r.status_code == 403
    r = client.post(
        "/api/v1/user/me/password",
        json={"current_password": "secret123", "new_password": "another123"},
        headers=headers,
    )
    assert r.status_code == 200
    new_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/user/me", headers=headers).status_code == 401
    assert client.get("/api/v1/user/me", headers=new_headers).status_code == 200

    r = client.request("DELETE", "/api/v1/user/me", json={"password": "bad"}, headers=new_headers)
    assert r.status_code == 403
    r = client.request("DELETE", "/api/v1/user/me", json={"password": "another123"}, headers=new_headers)
    assert r.status_code == 204
    assert client.get("/api/v1/user/me", headers=new_headers).status_code == 401


def test_delete_account_without_body_still_works(client):
    headers = register_and_login(client)
    assert client.delete("/api/v1/user/me", headers=headers).status_code == 204


def test_profile_update_validates(client):
    headers = register_and_login(client)
    assert client.patch("/api/v1/user/me", json={"language": "xx"}, headers=headers).status_code == 422
    r = client.patch("/api/v1/user/me", json={"language": "EN", "currency": "usd"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["language"] == "en" and r.json()["currency"] == "USD"


def test_web_delete_request_flow(client, monkeypatch):
    headers = register_and_login(client)
    client.post("/api/v1/favorites/", json={"title": "X", "price": 10, "link": "https://shop.example/x", "source": "Shop"}, headers=headers)
    sent = {}

    async def fake_send(email, token):
        sent["token"] = token

    monkeypatch.setattr("app.api.v1.endpoints.auth.send_delete_email", fake_send)
    known = client.post("/api/v1/auth/delete-request", json={"email": "USER@example.com"})
    unknown = client.post("/api/v1/auth/delete-request", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()  # no account enumeration
    raw = sent["token"]

    with SessionLocal() as db:
        assert db.query(User).first().delete_token == hash_reset_token(raw)

    # A second request inside the cooldown doesn't send another email.
    sent.clear()
    client.post("/api/v1/auth/delete-request", json={"email": "user@example.com"})
    assert "token" not in sent

    assert client.post("/api/v1/auth/delete-confirm", json={"token": "wrong"}).status_code == 400
    r = client.post("/api/v1/auth/delete-confirm", json={"token": raw})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.query(User).count() == 0
    assert client.get("/api/v1/user/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/delete-confirm", json={"token": raw}).status_code == 400


def test_web_delete_link_expires(client, monkeypatch):
    register_and_login(client)
    sent = {}

    async def fake_send(email, token):
        sent["token"] = token

    monkeypatch.setattr("app.api.v1.endpoints.auth.send_delete_email", fake_send)
    client.post("/api/v1/auth/delete-request", json={"email": "user@example.com"})
    with SessionLocal() as db:
        user = db.query(User).first()
        user.delete_token_expires = utcnow() - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/v1/auth/delete-confirm", json={"token": sent["token"]})
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.query(User).count() == 1
