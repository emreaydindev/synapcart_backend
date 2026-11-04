import type { Context, MiddlewareHandler } from "hono";
import type { Env } from "./env";
import type { UserRow } from "./db";
import { getUserByEmail } from "./db";
import { settings } from "./config";
import { decodeAccessToken } from "./lib/security";
import { ApiError, premiumRequired, rateLimited, unauthorized } from "./lib/errors";
import { isPremium } from "./services/plan";

export type AppEnv = { Bindings: Env; Variables: { user: UserRow } };
export type Ctx = Context<AppEnv>;

function bearer(c: Ctx): string | null {
  const auth = c.req.header("authorization") ?? "";
  return auth.toLowerCase().startsWith("bearer ") ? auth.slice(7).trim() : null;
}

export async function currentUser(c: Ctx): Promise<UserRow | null> {
  const token = bearer(c);
  if (!token) return null;
  const payload = await decodeAccessToken(c.env, token);
  if (!payload) return null;
  const user = await getUserByEmail(c.env.DB, payload.sub);
  // Tokens issued before the last password change are revoked.
  if (!user || payload.tv !== (user.token_version ?? 0)) return null;
  return user;
}

/** Requires a valid bearer token; sets `c.var.user`. */
export const requireUser: MiddlewareHandler<AppEnv> = async (c, next) => {
  const user = await currentUser(c);
  if (!user) throw unauthorized();
  c.set("user", user);
  await next();
};

export const requirePremium: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!isPremium(c.var.user)) throw premiumRequired();
  await next();
};

export const clientIp = (c: Ctx) =>
  c.req.header("cf-connecting-ip") ?? c.req.header("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";

type LimiterName = "AUTH_LIMITER" | "EMAIL_LIMITER" | "AGENT_LIMITER" | "BILLING_LIMITER";

/**
 * Workers Rate Limiting binding. Keyed by route + user id when authenticated,
 * otherwise route + client IP. No-op when the binding is absent or ENV=test.
 */
export function rateLimit(name: LimiterName, scope: string): MiddlewareHandler<AppEnv> {
  return async (c, next) => {
    const limiter = c.env[name];
    if (limiter && !settings(c.env).isTest) {
      const who = c.get("user")?.id ? `user:${c.get("user").id}` : `ip:${clientIp(c)}`;
      const { success } = await limiter.limit({ key: `${scope}:${who}` });
      if (!success) throw rateLimited();
    }
    await next();
  };
}

export function errorBody(err: ApiError) {
  const body: Record<string, unknown> = { detail: err.detail };
  if (err.code) body.code = err.code;
  const errors = (err as ApiError & { errors?: unknown }).errors;
  if (errors) body.errors = errors;
  return body;
}
