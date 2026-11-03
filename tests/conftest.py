import os
import tempfile

_tmpdir = tempfile.mkdtemp()
os.environ.update(
    {
        "ENV": "test",
        "AUTO_MIGRATE": "false",
        "DATABASE_URL": f"sqlite:///{_tmpdir}/test.db",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "GEMINI_API_KEY": "test",
        "SERP_API_KEY": "test",
        "SMTP_USER": "test@example.com",
        "SMTP_PASSWORD": "test",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.migrate import run_migrations  # noqa: E402
from app.main import app  # noqa: E402
from app.services import gemini_service, search_service  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.core.database import Base  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture(scope="session", autouse=True)
def migrated():
    run_migrations()
    yield


@pytest.fixture
def client():
    return TestClient(app)


class FakeAI:
    """Deterministic stand-ins for Gemini and SerpAPI."""

    def __init__(self):
        self.shopping = True
        self.products = [
            {"title": "Phone A", "price": 100.0, "source": "Shop", "link": "https://a.example", "thumbnail": None},
            {"title": "Phone B", "price": 200.0, "source": "Shop", "link": "https://b.example", "thumbnail": None},
        ]
        self.calls = []
        self.fail_search = False

    async def is_shopping_related(self, question, history=()):
        self.calls.append(("router", question, list(history)))
        return self.shopping

    async def extract_search_query(self, question, history=()):
        self.calls.append(("query", question, list(history)))
        return "phone"

    async def analyze_products(self, question, products, **kwargs):
        self.calls.append(("analyst", question, kwargs))
        return f"Best pick: {products[0]['title']}"

    async def search_products(self, query, language, currency, limit):
        if self.fail_search:
            raise search_service.SearchError("boom")
        return self.products[:limit]


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(gemini_service, "is_shopping_related", fake.is_shopping_related)
    monkeypatch.setattr(gemini_service, "extract_search_query", fake.extract_search_query)
    monkeypatch.setattr(gemini_service, "analyze_products", fake.analyze_products)
    import app.services.agent_service as agent_service

    monkeypatch.setattr(agent_service, "search_products", fake.search_products)
    return fake


def register_and_login(client, email="user@example.com", password="secret123", name="Ada"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
