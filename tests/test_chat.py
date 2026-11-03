import json

from tests.conftest import register_and_login


def _new_session(client, headers):
    r = client.post("/api/v1/chat/sessions", headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


def _events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_messages_require_owner(client, fake_ai):
    alice = register_and_login(client, email="alice@example.com")
    bob = register_and_login(client, email="bob@example.com")
    sid = _new_session(client, alice)
    client.post(f"/api/v1/chat/agent/{sid}", json={"message": "phone"}, headers=alice)

    assert client.get(f"/api/v1/chat/agent/{sid}/messages").status_code == 401
    assert client.get(f"/api/v1/chat/agent/{sid}/messages", headers=bob).status_code == 404
    r = client.get(f"/api/v1/chat/agent/{sid}/messages", headers=alice)
    assert r.status_code == 200 and len(r.json()) == 2


def test_stream_event_sequence_and_saved_answer(client, fake_ai):
    headers = register_and_login(client)
    sid = _new_session(client, headers)

    r = client.post(f"/api/v1/chat/agent/{sid}/stream", json={"message": "cheap phone"}, headers=headers)
    assert r.status_code == 200
    events = _events(r)
    assert [e["status"] for e in events] == ["routing", "searching", "thinking", "completed"]
    # Only the final event carries text; no internal status leaks.
    assert all("analysis" not in e for e in events[:-1])
    assert events[-1]["analysis"] == "Best pick: Phone A"
    assert len(events[-1]["products"]) == 2

    msgs = client.get(f"/api/v1/chat/agent/{sid}/messages", headers=headers).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "Best pick: Phone A"
    assert msgs[1]["products"][0]["title"] == "Phone A"

    sessions = client.get("/api/v1/chat/sessions", headers=headers).json()
    assert sessions[0]["title"] == "cheap phone"


def test_stream_refusal(client, fake_ai):
    fake_ai.shopping = False
    headers = register_and_login(client)
    sid = _new_session(client, headers)
    events = _events(client.post(f"/api/v1/chat/agent/{sid}/stream", json={"message": "weather?"}, headers=headers))
    assert [e["status"] for e in events] == ["routing", "out_of_scope"]
    assert "Ada" in events[-1]["analysis"]


def test_stream_error_event(client, fake_ai):
    fake_ai.fail_search = True
    headers = register_and_login(client)
    sid = _new_session(client, headers)
    events = _events(client.post(f"/api/v1/chat/agent/{sid}/stream", json={"message": "phone"}, headers=headers))
    assert events[-1]["status"] == "error"
    assert events[-1]["analysis"]


def test_no_products_skips_analyst(client, fake_ai):
    fake_ai.products = []
    headers = register_and_login(client)
    sid = _new_session(client, headers)
    r = client.post(f"/api/v1/chat/agent/{sid}", json={"message": "unobtainium"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "completed" and r.json()["products"] == []
    assert not any(c[0] == "analyst" for c in fake_ai.calls)


def test_history_passed_without_duplicate(client, fake_ai):
    headers = register_and_login(client)
    sid = _new_session(client, headers)
    client.post(f"/api/v1/chat/agent/{sid}", json={"message": "first"}, headers=headers)
    fake_ai.calls.clear()
    client.post(f"/api/v1/chat/agent/{sid}", json={"message": "cheaper one?"}, headers=headers)
    _, question, history = fake_ai.calls[0]
    assert question == "cheaper one?"
    assert history == ["Kullanıcı: first", "Asistan: Best pick: Phone A"]


def test_message_length_limit(client, fake_ai):
    headers = register_and_login(client)
    sid = _new_session(client, headers)
    r = client.post(f"/api/v1/chat/agent/{sid}", json={"message": "x" * 5000}, headers=headers)
    assert r.status_code == 422


def test_session_rename_and_delete(client, fake_ai):
    headers = register_and_login(client)
    other = register_and_login(client, email="other@example.com")
    sid = _new_session(client, headers)
    assert client.patch(f"/api/v1/chat/sessions/{sid}", json={"title": "x"}, headers=other).status_code == 404
    r = client.patch(f"/api/v1/chat/sessions/{sid}", json={"title": "Laptops"}, headers=headers)
    assert r.json()["title"] == "Laptops"
    assert client.delete(f"/api/v1/chat/sessions/{sid}", headers=headers).status_code == 204
    assert client.get("/api/v1/chat/sessions", headers=headers).json() == []
