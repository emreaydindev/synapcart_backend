# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

SynapCart backend: a FastAPI service for an AI shopping assistant. It handles auth, chat sessions with a LangGraph agent (Gemini plus Google Shopping search), favorites, user profiles and password-reset email. It is consumed by the Android app (`synapcart_mobile`) and the Next.js reset-password page (`synapcart_web`). The three repos are grouped as git submodules in the `synapcart` umbrella repo.

## Commands

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload   # Swagger UI at http://localhost:8001/docs
```

- Port **8001** is the convention: the mobile app and web portal expect the backend there when run locally.
- `httpx` is imported by `app/services/agent_service.py` but is missing from `requirements.txt`. Install it yourself if it is not pulled in transitively.
- There is no test suite, linter or formatter configured. `tests/*.json` are saved sample agent responses, not tests.

## Configuration

`app/core/config.py` uses pydantic-settings to load `.env`. These keys are required, and import fails without them: `GEMINI_API_KEY`, `SERP_API_KEY`, `DATABASE_URL`, `SECRET_KEY`, `SMTP_USER`, `SMTP_PASSWORD`. Optional keys with defaults: `APP_FRONTEND_URL`, `SMTP_SERVER`, `SMTP_PORT`, `RESET_TOKEN_EXPIRE_HOURS`. Because `settings` and the Gemini client are configured at import time, any import of `app.*` needs a valid `.env`.

`DATABASE_URL` can be SQLite (`sqlite:///./synapcart.db`, which gets `check_same_thread=False` automatically) or PostgreSQL (production on Render, via `psycopg2-binary`).

## Architecture

- **Entry:** `app/main.py` creates the app, applies open CORS and mounts `api/v1/api.py` under `/api/v1`. Routers are `/chat`, `/auth`, `/favorites`, `/user` (profiles), plus `/api/v1/health`.
- **Schema management:** tables come from `Base.metadata.create_all()` at startup. Alembic is listed in the requirements, but no migrations exist, so `create_all` won't change existing tables when a model changes. With SQLite, delete the local DB; with Postgres, alter the schema manually.
- **Auth:** HS256 JWT (`app/core/security.py`) with the user's **email** as `sub` and a 1-week expiry. In `app/api/deps.py`, `get_current_user_optional` returns `None` (guest) for a missing or invalid token. `get_current_user_required` raises 401. Passwords use `bcrypt` directly, not passlib. `User.id` is a UUID string, while chat and favorite IDs are integers.
- **Password reset:** `/auth/forgot-password` stores `reset_token` and `reset_token_expires` (1 hour) on the user and emails a link built by `build_reset_url()` as `{APP_FRONTEND_URL}/reset-password?token=...`. That URL is handled by the web portal (and by the app's deep links). The web portal POSTs `{token, new_password}` to `/auth/reset-password`. The email HTML lives in `security.py`. `services/email_service.py` is a separate, simpler sender.
- **Agent:** `app/services/agent_service.py`
  - `router_node` asks Gemini (`is_shopping_related`) whether the message is about shopping. If yes, it routes to `searcher`, then `analyst`. If no, it routes to `refusal`, which returns a canned message in the user's `language` (10 languages).
  - `searcher_node` asks Gemini for a single product-model keyword, then calls **SerpAPI** (`https://serpapi.com/search`, engine `google_shopping`) and keeps the top 3 results as `{title, price, source, link, thumbnail}`. The README says "Serper.dev", but the code calls SerpAPI. `services/search_service.get_serp_params` maps the user's `language` and `currency` to `hl`, `gl` and `location`.
  - `analyst_node` asks Gemini for a price/performance summary that addresses the user by name in their currency.
  - The compiled graph `app_agent` serves the non-streaming endpoint `POST /chat/agent/{id}`. The streaming endpoint `POST /chat/agent/{id}/stream` uses `stream_agent_invoke()`, a **hand-written** reimplementation of the same flow that emits SSE `data: {status, analysis, products?}` events (`routing` → `searching` → `thinking` → `completed`/`out_of_scope`/`error`). Graph changes must be mirrored in both places. The Android app parses these SSE events (`AgentStreamEvent`), so keep the field names stable.
  - Chat history passed to the agent is the last 6 DB messages, flattened into `"Kullanıcı: …"`/`"Asistan: …"` strings. `chat_service.save_message` also sets the session title from the first message, replacing the placeholder "Yeni Sohbet".
- **Gemini:** `app/services/gemini_service.py` uses the `google-generativeai` SDK with model `gemini-2.5-flash-lite`. Prompts are in Turkish.
- `app/agents/shopping_agent.get_system_prompt` is currently unused.

## Conventions

User-facing strings (HTTP `detail` messages, prompts, email text) are in **Turkish**. Keep new ones consistent. Logging is plain `print`.
