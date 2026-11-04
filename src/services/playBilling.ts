/** Google Play subscription verification (purchases.subscriptionsv2). */
import type { Env } from "../env";
import type { UserRow } from "../db";
import { getUserById, updateUser } from "../db";
import { settings } from "../config";
import { SCOPE_ANDROID_PUBLISHER, accessToken, loadServiceAccount, GoogleAuthError } from "./google";
import { PLAN_FREE, PLAN_PREMIUM, isPremium } from "./plan";

const API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications";

// States that still grant access until `expiryTime`.
const ENTITLED_STATES = new Set([
  "SUBSCRIPTION_STATE_ACTIVE",
  "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
  "SUBSCRIPTION_STATE_CANCELED", // cancelled but not yet expired
]);

export class BillingNotConfigured extends Error {}
/** Store API unreachable or returned an unexpected error. */
export class BillingError extends Error {}
/** The token/transaction is unknown or doesn't belong to this app/product. */
export class InvalidPurchase extends Error {}

export interface PlaySubscription {
  subscriptionState?: string;
  linkedPurchaseToken?: string;
  externalAccountIdentifiers?: { obfuscatedExternalAccountId?: string };
  lineItems?: { productId?: string; expiryTime?: string }[];
}

export async function fetchSubscription(env: Env, purchaseToken: string): Promise<PlaySubscription> {
  const account = loadServiceAccount(env.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON);
  if (!account) throw new BillingNotConfigured();
  let token: string;
  try {
    token = await accessToken(account, SCOPE_ANDROID_PUBLISHER);
  } catch (e) {
    if (e instanceof GoogleAuthError) throw new BillingError(e.message);
    throw e;
  }
  const url = `${API}/${settings(env).playPackageName}/purchases/subscriptionsv2/tokens/${encodeURIComponent(purchaseToken)}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15_000) });
  } catch (e) {
    throw new BillingError(`Play API request failed: ${(e as Error).name}`);
  }
  if ([400, 404, 410].includes(res.status)) throw new InvalidPurchase();
  if (!res.ok) throw new BillingError(`Play API returned ${res.status}`);
  return res.json();
}

/** [productId, expiryIso, entitled] for our subscription products. */
export function entitlement(env: Env, sub: PlaySubscription, now = new Date()): [string | null, string | null, boolean] {
  const ids = settings(env).playSubscriptionIds;
  let productId: string | null = null;
  let expiry: Date | null = null;
  for (const item of sub.lineItems ?? []) {
    if (!item.productId || !ids.includes(item.productId)) continue;
    const t = item.expiryTime ? new Date(item.expiryTime) : null;
    const valid = t && !Number.isNaN(t.getTime()) ? t : null;
    if (expiry === null || (valid && valid > expiry)) {
      productId = item.productId;
      expiry = valid;
    }
  }
  const entitled =
    productId !== null && ENTITLED_STATES.has(sub.subscriptionState ?? "") && expiry !== null && expiry > now;
  return [productId, expiry ? expiry.toISOString() : null, entitled];
}

/** Updates the user's plan from a Play subscription; returns the fresh row. */
export async function applySubscription(env: Env, user: UserRow, purchaseToken: string, sub: PlaySubscription) {
  const [productId, expiry, entitled] = entitlement(env, sub);
  // A resubscribe/upgrade replaces the old token (linkedPurchaseToken).
  const ids = { play_purchase_token: purchaseToken, play_product_id: productId };
  // An inactive Play subscription never downgrades an active App Store one.
  if (!entitled && user.plan_source === "apple" && isPremium(user)) return updateUser(env.DB, user.id, ids);
  const fresh = await updateUser(env.DB, user.id, {
    ...ids,
    plan_expires_at: expiry,
    plan: entitled ? PLAN_PREMIUM : PLAN_FREE,
    plan_source: "google",
  });
  console.log(`Plan updated from Play (user=${user.id}, state=${sub.subscriptionState}, entitled=${entitled})`);
  return fresh;
}

export async function findUserForToken(env: Env, purchaseToken: string, sub?: PlaySubscription): Promise<UserRow | null> {
  const byToken = (t: string) => env.DB.prepare("SELECT * FROM users WHERE play_purchase_token = ?").bind(t).first<UserRow>();
  let user = await byToken(purchaseToken);
  if (!user && sub) {
    if (sub.linkedPurchaseToken) user = await byToken(sub.linkedPurchaseToken);
    const accountId = sub.externalAccountIdentifiers?.obfuscatedExternalAccountId;
    if (!user && accountId) user = await getUserById(env.DB, accountId);
  }
  return user;
}

export const revoke = (env: Env, user: UserRow) =>
  user.plan_source === "apple" && isPremium(user)
    ? Promise.resolve(user) // the active entitlement comes from the App Store
    : updateUser(env.DB, user.id, { plan: PLAN_FREE, plan_expires_at: null });
