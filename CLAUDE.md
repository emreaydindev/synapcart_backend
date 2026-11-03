# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

SynapCart backend: a FastAPI service for an AI shopping assistant. It handles auth, chat sessions with a LangGraph agent (Gemini plus Google Shopping search), favorites, user profiles and password-reset email. It is consumed by the Android app (`synapcart_mobile`) and the Next.js reset-password page (`synapcart_web`). The three repos are grouped as git submodules in the `synapcart` umbrella repo.

## Commands

```bash
pip install -r requirements-dev.txt
cp .env.example .env                                         # then fill in keys
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload     # Swagger UI at http://localhost:8001/docs
pytest                                                       # all tests
pytest tests/test_chat.py::test_stream_refusal               # single test
python -m app.db.migrate                                     # apply migrations manually
alembic revision --autogenerate -m "msg"                     # new migration after a model change
alembic check                                                # verify models and migrations agree
```

- Port **8001** is the convention: the mobile app and web portal expect the backend there when run locally.
- Dependencies are pinned in `requirements.txt`; `requirements-dev.txt` adds pytest.
- Tests (`tests/`) run against a temp SQLite DB with `ENV=test` (rate limiting off). `tests/conftest.py`'s `fake_ai` fixture monkeypatches `gemini_service` functions and `agent_service.search_products`, so no API keys or network are needed. `tests/fixtures/*.json` are saved sample agent responses.
- No linter/formatter is configured.

## Configuration

`app/core/config.py` uses pydantic-settings to load `.env` (see `.env.example`). These keys are required, and import fails without them: `GEMINI_API_KEY`, `SERP_API_KEY`, `DATABASE_URL`, `SECRET_KEY`, `SMTP_USER`, `SMTP_PASSWORD`. Notable optional keys:
- `ENV`: `prod` disables `/docs` and requires a `SECRET_KEY` of at least 32 characters.
- `AUTO_MIGRATE`: run migrations on startup. It defaults to true; `render.yaml` sets it to false and migrates in the start command instead.
- `CORS_ORIGINS`: a comma-separated list.
- Also `ACCESS_TOKEN_EXPIRE_MINUTES` (default 1 week), `RESET_TOKEN_EXPIRE_HOURS`, `AGENT_RATE_LIMIT` and `MAX_MESSAGE_LENGTH`.

Because `settings` loads at import time, any import of `app.*` needs those env vars.

`DATABASE_URL` can be SQLite (`sqlite:///./synapcart.db`, which gets `check_same_thread=False` automatically) or PostgreSQL (production on Render, via `psycopg2-binary`).

## Architecture

- **Entry:** `app/main.py` creates the app and mounts `api/v1/api.py` under `/api/v1`. Routers are `/chat`, `/auth`, `/favorites`, `/user` (profiles), plus `/api/v1/health` (pings the DB). It also:
  - restricts CORS to `CORS_ORIGINS`;
  - registers the slowapi limiter;
  - adds exception handlers that keep every error body as `{"detail": "<string>"}`. Validation errors become a single readable message; a pydantic `ValueError("...")` message becomes the `detail`. Clients rely on `detail` being a string.
- **Schema management:** Alembic (`alembic/versions/`) is the source of truth; `create_all` is not used. `app/db/migrate.py` stamps legacy DBs (tables but no `alembic_version`) at `0001_baseline`, then runs `upgrade head`. Every model change needs a migration, and SQLite needs `render_as_batch` (already on). Keep model indexes and constraints identical to the migrations so `alembic check` stays clean.
- **Auth:**
  - HS256 JWT (`app/core/security.py`): `sub` is the user's **email**, `tv` is `User.token_version`, and expiry is `ACCESS_TOKEN_EXPIRE_MINUTES`.
  - `app/api/deps.py` rejects tokens whose `tv` is not the current version. Bumping `token_version` (password reset or change) revokes all issued tokens.
  - Emails are stored lowercased and looked up case-insensitively (`get_user_by_email`).
  - Password rules live in `schemas/user.validate_new_password`: 8–72 bytes, letters and digits.
  - Login failures return 401.
  - `/auth/token` is an OAuth2-form login for the Swagger "Authorize" button.
  - `User.id` is a UUID string; chat and favorite IDs are integers.
- **Rate limits** (`app/core/rate_limit.py`, slowapi, in-memory):
  - auth endpoints are limited per IP;
  - the agent endpoints use `AGENT_RATE_LIMIT` per user (`user_or_ip_key`);
  - limited endpoints must take a `request: Request` parameter;
  - in-memory storage means a single process. Use Redis `storage_uri` before scaling out.
- **Password reset:**
  - `/auth/forgot-password` stores the **SHA-256 hash** of the token and emails the raw token. It always returns the same message, even for unknown emails or SMTP failure, and has a 2-minute per-account cooldown.
  - The link is `{APP_FRONTEND_URL}/reset-password?token=...` (`build_reset_url`). The web portal and the app's deep links handle it, then POST `{token, new_password}` to `/auth/reset-password`.
  - The email HTML lives in `services/email_service.py`.
- **User endpoints:** `POST /user/me/password` (returns a fresh token) and `DELETE /user/me` (optional `{password}` body, verified if present).
- **Agent:** `app/services/agent_service.py`
  - **State:** `AgentState` holds plain values (`question`, `history`, `user_name`, `language`, `currency`, optional `max_products`/`analyst_model`), not ORM objects.
  - **Graph:** `router` → `searcher` → `analyst`, or `router` → `refusal`.
    - `router_node` calls `gemini_service.is_shopping_related`, which sees recent history so follow-ups count.
    - `searcher_node` gets a product-model query (`extract_search_query`), then calls `search_service.search_products`. That is **SerpAPI** `google_shopping`, with a 30-minute in-process TTL cache, keeping the top `max_products` (default 3) as `{title, price, source, link, thumbnail}`. `get_serp_params` maps language/currency to `hl`/`gl`/`location`.
    - `analyst_node` skips the LLM when there are no products. Otherwise `analyze_products` gets the question, history and products, and answers in the user's language.
    - `refusal` returns a canned localized message.
  - **Endpoints:**
    - `POST /chat/agent/{id}` calls `app_agent.ainvoke`.
    - `POST /chat/agent/{id}/stream` uses `stream_agent()`, which runs the **same graph** via `astream(stream_mode="updates")` and maps node completions to SSE `data:` events: `routing` → `searching` → `thinking` (+`products`) → `completed` (+`analysis`, `products`). It ends with `out_of_scope` (+`analysis`) for refusals and `error` (+`analysis`) on failure. Only final events carry `analysis`.
    - The Android app parses these (`AgentStreamEvent`), so keep the field names stable.
  - **History:** history is loaded *before* saving the new user message: the last 6 messages, flattened into `"Kullanıcı: …"`/`"Asistan: …"` strings. Assistant messages store `products` as JSON on `ChatMessage.products`, and `/messages` returns them parsed. The session title is set from the first user message, replacing "Yeni Sohbet".
  - **Persistence during streaming:** the stream saves the final answer with its own `SessionLocal()`, because the request DB session may already be closed.
- **Gemini:** `app/services/gemini_service.py` uses the `google-genai` SDK (`client.aio.models.generate_content`) with default model `gemini-2.5-flash-lite`. `generate()` adds a timeout and raises `GeminiError` on failure, blocked or empty output. Prompts are in Turkish and wrap user text in `<kullanici_mesaji>` delimiters.
- **Chat endpoints** check ownership via `chat_service.get_owned_session` (404 if not the caller's). Sessions can be listed newest-first, created, renamed (`PATCH`) and deleted.
- **Favorites:** `(user_id, link)` is unique. `POST /favorites/` is idempotent (200 with the existing row). It accepts `price` as a number or a string. There is also `DELETE /favorites/by-link?link=`. Responses include `currency` and `added_at`.

## Conventions

User-facing strings (HTTP `detail` messages, prompts, email text) are in **Turkish**. Agent replies, refusal and error messages are localized by `user.language` (`agent_service.localized`). Use `logging` (configured in `app/core/logging.py`) and never log message content or secrets. Use `app.core.database.utcnow()` (naive UTC) for timestamps.
