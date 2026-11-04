import asyncio
import base64
import json
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.database import SessionLocal, utcnow
from app.jobs import price_check
from app.models.favorite import Favorite
from app.models.usage import DeviceToken
from app.models.user import User
from app.services import billing_service, gemini_service, push_service
from tests.conftest import register_and_login

TOKEN_OK = "play-token-1"


def _set_plan(email="user@example.com", plan="premium", expires=None):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        user.plan = plan
        user.plan_expires_at = expires
        db.commit()
        return user.id


def _session(client, headers):
    return client.post("/api/v1/chat/sessions", headers=headers).json()["id"]


def _ask(client, headers, sid, message="phone"):
    return client.post(f"/api/v1/chat/agent/{sid}", json={"message": message}, headers=headers)


# --- Quota and tiering ---

def test_free_quota_returns_402_after_five(client, fake_ai):
    headers = register_and_login(client)
    sid = _session(client, headers)
    for _ in range(5):
        assert _ask(client, headers, sid).status_code == 200

    r = _ask(client, headers, sid)
    assert r.status_code == 402
    assert r.json()["code"] == "quota_exceeded" and isinstance(r.json()["detail"], str)
    r = client.post(f"/api/v1/chat/agent/{sid}/stream", json={"message": "x"}, headers=headers)
    assert r.status_code == 402 and r.json()["code"] == "quota_exceeded"

    me = client.get("/api/v1/user/me", headers=headers).json()
    assert me["plan"] == "free" and me["usage_today"] == 5 and me["daily_limit"] == 5
    assert me["plan_expires_at"] is None


def test_quota_not_spent_on_foreign_session(client, fake_ai):
    alice = register_and_login(client, email="alice@example.com")
    bob = register_and_login(client, email="bob@example.com")
    sid = _session(client, alice)
    assert _ask(client, bob, sid).status_code == 404
    assert client.get("/api/v1/user/me", headers=bob).json()["usage_today"] == 0


def test_tiers_set_products_and_model(client, fake_ai):
    fake_ai.products = [
        {"title": f"P{i}", "price": float(i), "source": "S", "link": f"https://{i}.example", "thumbnail": None}
        for i in range(10)
    ]
    headers = register_and_login(client)
    sid = _session(client, headers)
    assert len(_ask(client, headers, sid).json()["products"]) == 3
    assert fake_ai.calls[-1][2]["model_name"] == gemini_service.DEFAULT_MODEL

    _set_plan(expires=utcnow() + timedelta(days=30))
    assert len(_ask(client, headers, sid).json()["products"]) == 8
    assert fake_ai.calls[-1][2]["model_name"] == settings.PREMIUM_ANALYST_MODEL
    me = client.get("/api/v1/user/me", headers=headers).json()
    assert me["plan"] == "premium" and me["daily_limit"] == 100 and me["plan_expires_at"]


def test_expired_premium_is_free(client, fake_ai):
    headers = register_and_login(client)
    _set_plan(expires=utcnow() - timedelta(minutes=1))
    me = client.get("/api/v1/user/me", headers=headers).json()
    assert me["plan"] == "free" and me["daily_limit"] == 5


# --- History limit ---

def test_free_history_locks_older_sessions(client, fake_ai):
    headers = register_and_login(client)
    ids = [_session(client, headers) for _ in range(12)]
    sessions = client.get("/api/v1/chat/sessions", headers=headers).json()
    assert [s["id"] for s in sessions] == list(reversed(ids))
    assert [s["locked"] for s in sessions] == [False] * 10 + [True] * 2

    oldest = ids[0]
    r = client.get(f"/api/v1/chat/agent/{oldest}/messages", headers=headers)
    assert r.status_code == 402 and r.json()["code"] == "history_locked"
    assert _ask(client, headers, oldest).json()["code"] == "history_locked"
    # A locked question doesn't cost quota.
    assert client.get("/api/v1/user/me", headers=headers).json()["usage_today"] == 0
    # Locked sessions can still be deleted.
    assert client.delete(f"/api/v1/chat/sessions/{oldest}", headers=headers).status_code == 204

    _set_plan()
    sessions = client.get("/api/v1/chat/sessions", headers=headers).json()
    assert not any(s["locked"] for s in sessions)
    assert client.get(f"/api/v1/chat/agent/{ids[1]}/messages", headers=headers).status_code == 200


# --- Compare ---

PRODUCTS = [
    {"title": "Phone A", "price": 100, "source": "Shop", "link": "https://a.example"},
    {"title": "Phone B", "price": 200, "source": "Shop", "link": "https://b.example"},
]


def test_compare_requires_premium(client, fake_ai):
    headers = register_and_login(client)
    r = client.post("/api/v1/chat/compare", json={"products": PRODUCTS}, headers=headers)
    assert r.status_code == 402 and r.json()["code"] == "premium_required"


def test_compare_schema(client, monkeypatch):
    seen = {}

    async def fake_compare(products, **kwargs):
        seen.update(kwargs, n=len(products))
        return {
            "items": [{"title": "A", "pros": ["cheap", "light"], "cons": ["slow"]}],  # one item short
            "verdict": "Pick A.",
            "best_index": 0,
        }

    monkeypatch.setattr(gemini_service, "compare_products", fake_compare)
    headers = register_and_login(client)
    _set_plan()

    assert client.post("/api/v1/chat/compare", json={"products": PRODUCTS[:1]}, headers=headers).status_code == 422
    r = client.post("/api/v1/chat/compare", json={"products": PRODUCTS}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["title"] for i in body["items"]] == ["Phone A", "Phone B"]
    assert body["items"][0]["pros"] == ["cheap", "light"] and body["items"][1]["pros"] == []
    assert body["items"][0]["link"] == "https://a.example"
    assert body["verdict"] == "Pick A." and body["best_index"] == 0
    assert seen["language"] == "tr" and seen["n"] == 2


def test_compare_gemini_failure_is_502(client, monkeypatch):
    async def boom(products, **kwargs):
        raise gemini_service.GeminiError("x")

    monkeypatch.setattr(gemini_service, "compare_products", boom)
    headers = register_and_login(client)
    _set_plan()
    r = client.post("/api/v1/chat/compare", json={"products": PRODUCTS}, headers=headers)
    assert r.status_code == 502 and r.json()["detail"]


# --- Price alerts and device tokens ---

def _favorite(client, headers, **extra):
    body = {"title": "Phone A", "price": 120.0, "source": "Shop", "link": "https://a.example", **extra}
    return client.post("/api/v1/favorites/", json=body, headers=headers).json()


def test_price_target_is_premium(client):
    headers = register_and_login(client)
    fav = _favorite(client, headers)
    r = client.patch(f"/api/v1/favorites/{fav['id']}", json={"target_price": 100}, headers=headers)
    assert r.status_code == 402 and r.json()["code"] == "premium_required"

    _set_plan()
    r = client.patch(f"/api/v1/favorites/{fav['id']}", json={"target_price": 100}, headers=headers)
    assert r.status_code == 200 and r.json()["target_price"] == 100
    assert client.get("/api/v1/favorites/", headers=headers).json()[0]["target_price"] == 100
    assert client.patch(f"/api/v1/favorites/{fav['id']}", json={"target_price": -1}, headers=headers).status_code == 422
    r = client.patch(f"/api/v1/favorites/{fav['id']}", json={"target_price": None}, headers=headers)
    assert r.json()["target_price"] is None


def test_device_token_register_move_delete(client):
    alice = register_and_login(client, email="alice@example.com")
    bob = register_and_login(client, email="bob@example.com")
    assert client.post("/api/v1/user/me/device-token", json={"token": "t1"}, headers=alice).status_code == 204
    assert client.post("/api/v1/user/me/device-token", json={"token": "t1"}, headers=bob).status_code == 204
    with SessionLocal() as db:
        rows = db.query(DeviceToken).all()
        assert len(rows) == 1
        bob_id = db.query(User).filter(User.email == "bob@example.com").one().id
        assert rows[0].user_id == bob_id
    r = client.request("DELETE", "/api/v1/user/me/device-token", json={"token": "t1"}, headers=bob)
    assert r.status_code == 204
    with SessionLocal() as db:
        assert db.query(DeviceToken).count() == 0


def test_price_check_job(client, monkeypatch):
    headers = register_and_login(client)
    _set_plan()
    fav = _favorite(client, headers)
    client.patch(f"/api/v1/favorites/{fav['id']}", json={"target_price": 100}, headers=headers)
    client.post("/api/v1/user/me/device-token", json={"token": "dev-1"}, headers=headers)

    price = {"value": 95.0}
    sent = []

    async def fake_search(query, language, currency, limit):
        assert query == "Phone A"
        return [
            {"title": "Other", "price": 10.0, "source": "X", "link": "https://other.example"},
            {"title": "Phone A", "price": price["value"], "source": "Shop", "link": "https://a.example"},
        ]

    async def fake_send(token, title, body, data=None):
        sent.append((token, title, data))

    monkeypatch.setattr(price_check, "search_products", fake_search)
    monkeypatch.setattr(push_service, "send", fake_send)
    monkeypatch.setattr(push_service, "is_configured", lambda: True)

    def run():
        with SessionLocal() as db:
            return asyncio.run(price_check.run(db))

    assert run()["notified"] == 1
    assert sent[0][0] == "dev-1" and sent[0][1] == "Fiyat düştü!"
    assert sent[0][2]["type"] == "price_alert" and sent[0][2]["link"] == "https://a.example"
    # Same price again: no duplicate alert.
    assert run()["notified"] == 0
    price["value"] = 90.0
    assert run()["notified"] == 1
    # Above target: nothing.
    price["value"] = 150.0
    assert run()["notified"] == 0
    fav_now = client.get("/api/v1/favorites/", headers=headers).json()[0]
    assert fav_now["last_checked_price"] == 150.0

    # Expired premium is skipped entirely.
    _set_plan(expires=utcnow() - timedelta(days=1))
    assert run()["checked"] == 0


def test_price_check_drops_unregistered_tokens(client, monkeypatch):
    headers = register_and_login(client)
    _set_plan()
    fav = _favorite(client, headers)
    client.patch(f"/api/v1/favorites/{fav['id']}", json={"target_price": 200}, headers=headers)
    client.post("/api/v1/user/me/device-token", json={"token": "dead"}, headers=headers)

    async def fake_search(query, language, currency, limit):
        return [{"title": "Phone A", "price": 120.0, "source": "Shop", "link": "https://a.example"}]

    async def fake_send(token, title, body, data=None):
        raise push_service.InvalidToken()

    monkeypatch.setattr(price_check, "search_products", fake_search)
    monkeypatch.setattr(push_service, "send", fake_send)
    monkeypatch.setattr(push_service, "is_configured", lambda: True)
    with SessionLocal() as db:
        assert asyncio.run(price_check.run(db))["notified"] == 0
        assert db.query(DeviceToken).count() == 0
        # Not marked as notified, so a later registered device still gets it.
        assert db.get(Favorite, fav["id"]).last_notified_price is None


# --- Billing ---

def _subscription(state="SUBSCRIPTION_STATE_ACTIVE", days=30, product="synapcart_premium", account=None):
    expiry = (utcnow() + timedelta(days=days)).isoformat() + "Z"
    sub = {"subscriptionState": state, "lineItems": [{"productId": product, "expiryTime": expiry}]}
    if account:
        sub["externalAccountIdentifiers"] = {"obfuscatedExternalAccountId": account}
    return sub


@pytest.fixture
def play(monkeypatch):
    subs = {}

    async def fake_fetch(token):
        if token not in subs:
            raise billing_service.InvalidPurchase()
        return subs[token]

    monkeypatch.setattr(billing_service, "fetch_subscription", fake_fetch)
    monkeypatch.setattr(settings, "PLAY_RTDN_TOKEN", "rtdn-secret")
    return subs


def _verify(client, headers, token=TOKEN_OK, product="synapcart_premium"):
    return client.post(
        "/api/v1/billing/google/verify",
        json={"purchase_token": token, "product_id": product},
        headers=headers,
    )


def test_verify_activates_premium(client, play):
    headers = register_and_login(client)
    user_id = _set_plan(plan="free")
    play[TOKEN_OK] = _subscription(account=user_id)

    r = _verify(client, headers)
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "premium" and r.json()["plan_expires_at"]
    assert client.get("/api/v1/user/me", headers=headers).json()["daily_limit"] == 100

    assert _verify(client, headers, product="other").status_code == 400
    assert _verify(client, headers, token="unknown").status_code == 400


def test_verify_rejects_other_accounts_purchase(client, play):
    alice = register_and_login(client, email="alice@example.com")
    bob = register_and_login(client, email="bob@example.com")
    alice_id = _set_plan(email="alice@example.com", plan="free")
    play[TOKEN_OK] = _subscription(account=alice_id)
    assert _verify(client, bob).status_code == 409
    assert _verify(client, alice).status_code == 200
    # Without an account id, the token is still bound to its first owner.
    play[TOKEN_OK] = _subscription()
    assert _verify(client, bob).status_code == 409


def test_verify_expired_subscription_stays_free(client, play):
    headers = register_and_login(client)
    play[TOKEN_OK] = _subscription(state="SUBSCRIPTION_STATE_EXPIRED", days=-1)
    assert _verify(client, headers).json()["plan"] == "free"


def test_verify_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "")
    headers = register_and_login(client)
    assert _verify(client, headers).status_code == 503


def _rtdn(client, payload, token="rtdn-secret"):
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return client.post(
        f"/api/v1/billing/google/rtdn?token={token}",
        json={"message": {"data": data, "messageId": "1"}, "subscription": "projects/x/subscriptions/y"},
    )


def test_rtdn_updates_plan(client, play):
    headers = register_and_login(client)
    play[TOKEN_OK] = _subscription()
    _verify(client, headers)

    note = {
        "packageName": settings.PLAY_PACKAGE_NAME,
        "subscriptionNotification": {"notificationType": 13, "purchaseToken": TOKEN_OK, "subscriptionId": "synapcart_premium"},
    }
    assert _rtdn(client, note, token="wrong").status_code == 403

    play[TOKEN_OK] = _subscription(state="SUBSCRIPTION_STATE_EXPIRED", days=-1)
    assert _rtdn(client, note).status_code == 204
    assert client.get("/api/v1/user/me", headers=headers).json()["plan"] == "free"

    # Renewal on a new linked token moves the plan to it.
    play["play-token-2"] = {**_subscription(), "linkedPurchaseToken": TOKEN_OK}
    note["subscriptionNotification"]["purchaseToken"] = "play-token-2"
    assert _rtdn(client, note).status_code == 204
    assert client.get("/api/v1/user/me", headers=headers).json()["plan"] == "premium"

    # Voided purchase revokes; test and unknown notifications are acked.
    assert _rtdn(client, {"voidedPurchaseNotification": {"purchaseToken": "play-token-2"}}).status_code == 204
    assert client.get("/api/v1/user/me", headers=headers).json()["plan"] == "free"
    assert _rtdn(client, {"testNotification": {"version": "1.0"}}).status_code == 204


def test_entitlement_canceled_until_expiry():
    _, expiry, entitled = billing_service.entitlement(_subscription(state="SUBSCRIPTION_STATE_CANCELED", days=3))
    assert entitled and expiry > utcnow()
    _, _, entitled = billing_service.entitlement(_subscription(state="SUBSCRIPTION_STATE_ON_HOLD"))
    assert not entitled
    _, _, entitled = billing_service.entitlement(_subscription(product="unknown"))
    assert not entitled
