/**
 * Plans, limits and the daily message quota.
 *
 * The limits are mirrored on the web landing page (synapcart_web/lib/site.ts
 * `plans`) and in the mobile paywall copy (Android strings, iOS String Catalog);
 * change them together.
 */
import type { Env } from "../env";
import type { UserRow } from "../db";
import { settings } from "../config";
import { isPast, todayUtc } from "../lib/time";
import { DEFAULT_MODEL } from "./gemini";

export const PLAN_FREE = "free";
export const PLAN_PREMIUM = "premium";

export interface PlanLimits {
  plan: string;
  dailyMessages: number;
  maxProducts: number;
  analystModel: string;
  maxSessions: number | null; // null = unlimited history
  compare: boolean;
  priceAlerts: boolean;
}

export function limitsFor(env: Env, plan: string): PlanLimits {
  if (plan === PLAN_PREMIUM) {
    return {
      plan: PLAN_PREMIUM,
      dailyMessages: 100, // soft cap against abuse
      maxProducts: 8,
      analystModel: settings(env).premiumAnalystModel,
      maxSessions: null,
      compare: true,
      priceAlerts: true,
    };
  }
  return {
    plan: PLAN_FREE,
    dailyMessages: 5,
    maxProducts: 3,
    analystModel: DEFAULT_MODEL,
    maxSessions: 10,
    compare: false,
    priceAlerts: false,
  };
}

/** Premium only while it hasn't expired; a missing expiry means a manual grant. */
export function effectivePlan(user: Pick<UserRow, "plan" | "plan_expires_at">, now = new Date()): string {
  if (user.plan !== PLAN_PREMIUM) return PLAN_FREE;
  if (isPast(user.plan_expires_at, now)) return PLAN_FREE;
  return PLAN_PREMIUM;
}

export const getLimits = (env: Env, user: UserRow) => limitsFor(env, effectivePlan(user));
export const isPremium = (user: UserRow) => effectivePlan(user) === PLAN_PREMIUM;

export async function usageToday(db: D1Database, userId: string): Promise<number> {
  const row = await db
    .prepare("SELECT messages FROM usage_daily WHERE user_id = ? AND date = ?")
    .bind(userId, todayUtc())
    .first<{ messages: number }>();
  return row?.messages ?? 0;
}

/** Counts one agent message for today (atomic upsert); returns the new total. */
export async function recordMessage(db: D1Database, userId: string): Promise<number> {
  const row = await db
    .prepare(
      `INSERT INTO usage_daily (user_id, date, messages) VALUES (?, ?, 1)
       ON CONFLICT (user_id, date) DO UPDATE SET messages = messages + 1
       RETURNING messages`,
    )
    .bind(userId, todayUtc())
    .first<{ messages: number }>();
  return row?.messages ?? 0;
}
