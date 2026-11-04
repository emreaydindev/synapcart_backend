import { applyD1Migrations, env } from "cloudflare:test";
import { afterEach, beforeEach, vi } from "vitest";
import { clearTokenCache } from "../src/services/google";
import { outbox } from "../src/services/email";

await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);

beforeEach(async () => {
  await env.DB.batch(
    ["device_tokens", "usage_daily", "favorites", "chat_messages", "chat_sessions", "users"].map((t) =>
      env.DB.prepare(`DELETE FROM ${t}`),
    ),
  );
  clearTokenCache();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  outbox.capture = undefined;
});
