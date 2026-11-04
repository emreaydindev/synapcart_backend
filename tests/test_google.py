import asyncio
import json

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.core.config import settings
from app.services import google_auth, push_service


def _account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    account = {
        "type": "service_account",
        "project_id": "synapcart-test",
        "private_key_id": "kid1",
        "private_key": pem,
        "client_email": "bot@synapcart-test.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return account, public


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_service_account_token_and_fcm_send(monkeypatch):
    account, public = _account()
    google_auth._cache.clear()
    monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps(account))
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            claims = jwt.decode(form["assertion"], public, algorithms=["RS256"], audience=account["token_uri"])
            assert claims["iss"] == account["client_email"]
            assert claims["scope"] == google_auth.SCOPE_FCM
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer at-1"
        return httpx.Response(200, json={"name": "projects/synapcart-test/messages/1"})

    _mock_client(monkeypatch, handler)
    assert push_service.is_configured()
    asyncio.run(push_service.send("device", "Title", "Body", {"favorite_id": 3}))
    asyncio.run(push_service.send("device", "Title", "Body"))

    # The token is cached: one exchange, two sends.
    assert [r.url.host for r in requests] == ["oauth2.googleapis.com", "fcm.googleapis.com", "fcm.googleapis.com"]
    assert requests[1].url.path == "/v1/projects/synapcart-test/messages:send"
    message = json.loads(requests[1].content)["message"]
    assert message["token"] == "device" and message["data"] == {"favorite_id": "3"}
    assert message["android"]["notification"]["channel_id"] == "price_alerts"


def test_fcm_unregistered_token(monkeypatch):
    account, _ = _account()
    google_auth._cache.clear()
    monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps(account))

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})

    _mock_client(monkeypatch, handler)
    try:
        asyncio.run(push_service.send("gone", "t", "b"))
        raise AssertionError("expected InvalidToken")
    except push_service.InvalidToken:
        pass


def test_push_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "")
    assert not push_service.is_configured()
