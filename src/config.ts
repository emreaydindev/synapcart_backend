import type { Env } from "./env";
import { MAX_ITERATIONS, MIN_ITERATIONS } from "./lib/password";

const list = (v: string | undefined, fallback: string[]): string[] =>
  v === undefined ? fallback : v.split(",").map((s) => s.trim()).filter(Boolean);

export interface Settings {
  env: string;
  isProd: boolean;
  isTest: boolean;
  corsOrigins: string[];
  frontendUrl: string;
  emailFrom: string;
  passwordIterations: number;
  accessTokenMinutes: number;
  resetTokenHours: number;
  deleteTokenHours: number;
  maxMessageLength: number;
  geminiTimeoutMs: number;
  premiumAnalystModel: string;
  playPackageName: string;
  playSubscriptionIds: string[];
  appleBundleId: string;
  appleAppId: number | undefined;
  appleProductIds: string[];
  appleEnvironment: "Production" | "Sandbox";
}

const cache = new WeakMap<Env, Settings>();

export function settings(env: Env): Settings {
  const hit = cache.get(env);
  if (hit) return hit;
  const name = (env.ENV || "dev").toLowerCase();
  const isProd = name === "prod" || name === "production";
  if (!env.SECRET_KEY || (isProd && env.SECRET_KEY.length < 32)) {
    throw new Error("SECRET_KEY must be set (at least 32 characters in production). Generate one with: openssl rand -base64 48");
  }
  const s: Settings = {
    env: name,
    isProd,
    isTest: name === "test",
    corsOrigins: list(env.CORS_ORIGINS, ["https://synapcart.emreaydin.dev", "http://localhost:3000"]),
    frontendUrl: (env.APP_FRONTEND_URL || "https://synapcart.emreaydin.dev").replace(/\/$/, ""),
    emailFrom: env.EMAIL_FROM || "noreply@synapcart.emreaydin.dev",
    passwordIterations: Math.min(MAX_ITERATIONS, Math.max(MIN_ITERATIONS, Number(env.PASSWORD_ITERATIONS) || MAX_ITERATIONS)),
    accessTokenMinutes: Number(env.ACCESS_TOKEN_EXPIRE_MINUTES) || 60 * 24 * 7,
    resetTokenHours: 1,
    deleteTokenHours: 24,
    maxMessageLength: 1000,
    geminiTimeoutMs: 30_000,
    premiumAnalystModel: env.PREMIUM_ANALYST_MODEL || "gemini-2.5-flash",
    playPackageName: env.PLAY_PACKAGE_NAME || "com.neilb.synapcart",
    playSubscriptionIds: list(env.PLAY_SUBSCRIPTION_IDS, ["synapcart_premium"]),
    appleBundleId: env.APPLE_BUNDLE_ID || "com.neilb.synapcart",
    appleAppId: env.APPLE_APP_ID ? Number(env.APPLE_APP_ID) : undefined,
    appleProductIds: list(env.APPLE_PRODUCT_IDS, ["synapcart_premium_monthly", "synapcart_premium_yearly"]),
    appleEnvironment: env.APPLE_ENVIRONMENT === "Sandbox" ? "Sandbox" : "Production",
  };
  cache.set(env, s);
  return s;
}
