# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

SynapCart backend: a TypeScript **Cloudflare Worker** (Hono) on **D1**. It is the API for an AI shopping assistant and handles:
- auth;
- chat sessions with the shopping agent (Gemini plus SerpAPI Google Shopping);
- favorites and user profiles;
- the free/Premium plan and daily quota;
- Google Play **and** App Store subscription billing;
- FCM price alerts (Android and iOS);
- AI product comparison;
- password-reset and account-deletion email (Resend HTTP API; the Cloudflare Email Service binding is a fallback for Workers Paid).

Its clients are the mobile apps (`synapcart_mobile`: a shared KMP module plus Android Compose and iOS SwiftUI apps) and the Next.js web portal (`synapcart_web`). All three repos are submodules of the `synapcart` umbrella repo. Production is `https://api.synapcart.emreaydin.dev`; staging is `https://staging-api.synapcart.emreaydin.dev`.

Until v2 this was a FastAPI/LangGraph/Postgres service on Render. The HTTP contract was kept identical during the port, so look in git history for the Python original.

## Commands

```bash
npm install                       # .npmrc sets legacy-peer-deps (vitest-plugin peer range)
npm run dev -- --port 8001        # wrangler dev; needs .dev.vars (copy .dev.vars.example)
npm run db:migrate:local          # apply migrations/ to the local D1
npm test                          # vitest in workerd (@cloudflare/vitest-plugin)
npx vitest run test/chat.test.ts -t "streams"   # single test
npm run typecheck
npm run deploy:staging / deploy:prod            # prod uses --env="" (top-level env)
npx wrangler d1 migrations create DB <name>     # new migration
```

Port **8001** is the local convention; the apps' debug builds and the web portal expect it.

## Layout

- **`src/index.ts`** exports `fetch` (the Hono `app`) and `scheduled`, the daily Cron Trigger. The cron runs `runPriceCheck` and `refreshAppleSubscriptions`.
- **`src/app.ts`** handles CORS (only `CORS_ORIGINS`; no credentials) and error mapping, mounts the routers under `/api/v1`, and serves `/api/v1/health`.
- **`src/config.ts`**: `settings(env)` parses vars once per env object; its defaults are the production values. **`src/env.ts`** types the bindings.
- **`src/context.ts`**
  - `requireUser` sets `c.var.user`, and `requirePremium` follows it.
  - `rateLimit(binding, scope)` uses the Workers Rate Limiting bindings. It is keyed by user id or client IP and is a no-op when `ENV=test` or the binding is absent.
- **`src/routes/*`**: `auth`, `user` (`/user/me`…), `chat` (sessions, messages, agent, `stream`, compare), `favorites`, `billing` (google verify/rtdn, apple verify/notifications).
- **`src/services/*`**
  - `agent.ts` is the state machine.
  - `gemini.ts` holds the REST calls and prompts.
  - `search.ts` covers SerpAPI and the Cache API.
  - `plan.ts` holds the limits and quota.
  - `chat.ts` covers history and saving messages.
  - `email.ts` holds the templates and sends through Resend (`RESEND_API_KEY`), else the `SEND_EMAIL` binding, else logs.
  - `google.ts` mints service-account tokens with `jose`.
  - `push.ts` sends FCM v1.
  - `playBilling.ts` and `appleBilling.ts` handle store billing.
  - `profile.ts` builds the `/user/me` response.
- **`src/lib/*`**
  - `validation.ts` holds the zod schemas and turns validation errors into a single readable `detail`.
  - `errors.ts` defines `ApiError`, rendered as `{detail, code?}`.
  - `password.ts` implements PBKDF2.
  - `security.ts` handles JWTs and link builders.
  - `crypto.ts` and `time.ts` are helpers.
- **`src/db.ts`** holds the row types and user helpers. Queries are plain D1 prepared statements, with no ORM.
- **`migrations/`** is the D1 schema and the source of truth. D1 enforces foreign keys, and user deletion cascades to every child table. Timestamps are ISO-8601 UTC strings from `nowIso()`.

## Behaviour that clients depend on

- **Error bodies**
  - Every error is `{"detail": "<string>"}`, and validation errors are 422 with one readable `detail`.
  - A zod `custom` issue message becomes the `detail` verbatim; other issues become `Geçersiz alan: <field>`.
  - Plan errors are 402 with `code` `quota_exceeded`, `premium_required` or `history_locked`; the apps open the paywall on these. Rate-limit errors are 429 `rate_limited`.
- **Auth**
  - The JWT is HS256. `sub` is the user's **email**, `tv` is `token_version`, and tokens last 7 days.
  - Bumping `token_version` (password reset or change) revokes every token.
  - Emails are lowercased and compared case-insensitively (`COLLATE NOCASE`).
  - Password rules: 8–72 bytes, letters and digits.
  - Passwords are hashed with PBKDF2-SHA256 at `PASSWORD_ITERATIONS` (10k–100k, default 100k; `wrangler.jsonc` sets 25k to fit the Workers Free 10 ms CPU limit) in the format `pbkdf2_sha256$iter$salt$hash`. Login rehashes when the stored count differs from the setting.
  - `/auth/token` is a form login, disabled in prod.
- **Reset and deletion links**
  - Tokens are stored as SHA-256 hashes.
  - There is a 2-minute per-account cooldown.
  - The same message is returned for unknown emails and for send failures.
  - Links are `{APP_FRONTEND_URL}/reset-password?token=…` and `/delete-account?token=…`.
- **Agent:** see `services/agent.ts`.
  - **Flow:** router (`isShoppingRelated`), then searcher (`extractSearchQuery` → `searchProducts`, top `maxProducts`), then analyst. When there are no products, the analyst is skipped. Otherwise the route ends in a localized refusal.
  - **SSE events:** `routing` → `searching` → `thinking` (+`products`) → `completed` (+`analysis`, `products`). A refusal ends with `out_of_scope` (+`analysis`) and a failure with `error` (+`analysis`). Only final events carry `analysis`, and the apps parse these field names.
  - **History:** the last 6 messages are loaded *before* the new question is saved.
  - **Saved data:** assistant messages store `products` as JSON. The session title comes from the first question.
  - **Tests:** they spy on `defaultDeps`.
- **Quota** (`plan.ts`)
  - Free: 5 messages/day, 3 products, flash-lite, the 10 newest sessions. Premium: 100/day, 8 products, `PREMIUM_ANALYST_MODEL`, unlimited history.
  - Premium counts only while `plan_expires_at` is in the future (NULL = manual grant).
  - The quota is checked first. Ownership, then the lock, are checked before `recordMessage`, so a 404 or a locked session costs nothing.
  - These numbers are mirrored in `synapcart_web/lib/site.ts`, the Android strings and the iOS String Catalog.
- **Billing**
  - `plan_source` is `google` or `apple`. An inactive subscription from one store never downgrades active premium from the other.
  - `POST /billing/google/verify` uses `subscriptionsv2`. It returns 409 if `obfuscatedExternalAccountId` or the stored token belongs to another user. RTDN is `?token=PLAY_RTDN_TOKEN`.
  - `POST /billing/apple/verify {signed_transaction}` (StoreKit 2 `jwsRepresentation`):
    - `verifySignedData` checks the x5c chain to the pinned Apple Root CA G3 fingerprint, the Apple marker OIDs on the intermediate and leaf, cert validity at `signedDate`, and the ES256 signature (`node:crypto` X509Certificate plus `jose`).
    - It then checks bundle, product and environment.
    - `appAccountToken` must equal the user id, and an `originalTransactionId` owned by another user returns 409.
  - `POST /billing/apple/notifications` handles App Store Server Notifications V2. Refunds and revokes downgrade the plan; renewals update the expiry. An unknown transaction is acknowledged with 200.
  - With `APPLE_ISSUER_ID`, `APPLE_KEY_ID` and `APPLE_PRIVATE_KEY` set, verify prefers the App Store Server API's latest status, and the cron refreshes lapsed Apple subscriptions.
  - Tests swap `appleTrust.rootFingerprints` for the chain in `test/fixtures/apple`.
- **Price alerts:** `PATCH /favorites/{id}` (premium) sets `target_price`, and `null` re-arms the alert. Device tokens are FCM tokens for both platforms (`platform` is `android` or `ios`). The cron re-searches by title, matches by link or by store+title, and notifies once per drop. Dead tokens are deleted.
- **Favorites:** `(user_id, link)` is unique, and POST is idempotent (an existing favorite returns 200). `price` may be a string such as `"1.299,50"`. `DELETE /favorites/by-link?link=` is supported. Responses use `added_at`.

## Conventions

- User-facing strings (`detail`, prompts, email copy) are in **Turkish**. Agent replies, refusals and push copy are localized by `user.language` (`localized()`).
- Never log message content, tokens or secrets.
- Outbound calls use global `fetch` with `AbortSignal.timeout`, which is how the tests mock them (`mockFetch`).
- The test suite starts each test with empty tables (`test/setup.ts`). The search cache is disabled in `ENV=test`.
