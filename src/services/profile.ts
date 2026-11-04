import type { Env } from "../env";
import type { UserRow } from "../db";
import { PLAN_PREMIUM, getLimits, usageToday } from "./plan";

/** The profile shape returned by /user/me, the billing endpoints and /auth/register. */
export async function profileResponse(env: Env, user: UserRow) {
  const limits = getLimits(env, user);
  return {
    id: user.id,
    email: user.email,
    full_name: user.full_name,
    language: user.language,
    currency: user.currency,
    created_at: user.created_at,
    plan: limits.plan,
    plan_expires_at: limits.plan === PLAN_PREMIUM ? user.plan_expires_at : null,
    plan_source: limits.plan === PLAN_PREMIUM ? user.plan_source : null,
    usage_today: await usageToday(env.DB, user.id),
    daily_limit: limits.dailyMessages,
  };
}
