import { Hono } from "hono";
import type { AppEnv } from "../context";
import { rateLimit, requireUser } from "../context";
import { settings } from "../config";
import { ApiError } from "../lib/errors";
import { b64Decode, safeEqual } from "../lib/crypto";
import { parseJson, schemas } from "../lib/validation";
import * as play from "../services/playBilling";
import * as apple from "../services/appleBilling";
import { profileResponse } from "../services/profile";

const billing = new Hono<AppEnv>();

const OTHER_ACCOUNT = "Bu abonelik başka bir hesaba ait.";

// --- Google Play ---

/** Validates a Play subscription purchase and updates the plan. The app acknowledges it afterwards. */
billing.post("/google/verify", requireUser, rateLimit("BILLING_LIMITER", "verify"), async (c) => {
  const body = await parseJson(c, schemas.playVerify);
  const user = c.var.user;
  if (!settings(c.env).playSubscriptionIds.includes(body.product_id)) throw new ApiError(400, "Bilinmeyen abonelik ürünü.");

  let sub: play.PlaySubscription;
  try {
    sub = await play.fetchSubscription(c.env, body.purchase_token);
  } catch (e) {
    if (e instanceof play.BillingNotConfigured) throw new ApiError(503, "Ödeme doğrulama şu an kullanılamıyor.");
    if (e instanceof play.InvalidPurchase) throw new ApiError(400, "Satın alma doğrulanamadı.");
    console.error("Play verification failed", (e as Error).message);
    throw new ApiError(502, "Satın alma şu an doğrulanamadı, lütfen tekrar deneyin.");
  }
  // The app passes the user id as obfuscatedAccountId; refuse someone else's purchase.
  const accountId = sub.externalAccountIdentifiers?.obfuscatedExternalAccountId;
  if (accountId && accountId !== user.id) throw new ApiError(409, OTHER_ACCOUNT);
  const owner = await play.findUserForToken(c.env, body.purchase_token);
  if (owner && owner.id !== user.id) throw new ApiError(409, OTHER_ACCOUNT);

  const fresh = await play.applySubscription(c.env, user, body.purchase_token, sub);
  return c.json(await profileResponse(c.env, fresh));
});

/**
 * Pub/Sub push endpoint for Play Real-time Developer Notifications.
 * Push URL: https://api.synapcart.emreaydin.dev/api/v1/billing/google/rtdn?token=<PLAY_RTDN_TOKEN>
 * Any 2xx acks the message; a 5xx makes Pub/Sub retry.
 */
billing.post("/google/rtdn", async (c) => {
  const token = c.req.query("token") ?? "";
  if (!c.env.PLAY_RTDN_TOKEN || !safeEqual(token, c.env.PLAY_RTDN_TOKEN)) throw new ApiError(403, "Forbidden");
  const body = await parseJson(c, schemas.pubsub);

  let payload: any;
  try {
    payload = JSON.parse(new TextDecoder().decode(b64Decode(body.message.data || "")) || "{}");
  } catch {
    console.warn(`RTDN with undecodable data (id=${body.message.messageId})`);
    return c.body(null, 204);
  }
  if (payload.packageName && payload.packageName !== settings(c.env).playPackageName) return c.body(null, 204);

  const voided = payload.voidedPurchaseNotification;
  if (voided?.purchaseToken) {
    const user = await play.findUserForToken(c.env, voided.purchaseToken);
    if (user) {
      await play.revoke(c.env, user);
      console.log(`Purchase voided; plan revoked (user=${user.id})`);
    }
    return c.body(null, 204);
  }

  const notification = payload.subscriptionNotification;
  if (!notification?.purchaseToken) return c.body(null, 204); // testNotification or one-time products

  let sub: play.PlaySubscription;
  try {
    sub = await play.fetchSubscription(c.env, notification.purchaseToken);
  } catch (e) {
    if (e instanceof play.InvalidPurchase) return c.body(null, 204);
    console.error("RTDN: could not fetch subscription", (e as Error).message);
    throw new ApiError(503, "Unavailable");
  }
  const user = await play.findUserForToken(c.env, notification.purchaseToken, sub);
  if (!user) {
    // Not verified by the app yet; /google/verify will pick it up.
    console.log(`RTDN for unknown token (type=${notification.notificationType})`);
    return c.body(null, 204);
  }
  await play.applySubscription(c.env, user, notification.purchaseToken, sub);
  return c.body(null, 204);
});

// --- App Store ---

/**
 * Validates a StoreKit 2 signed transaction (Transaction.jwsRepresentation) and
 * updates the plan. The app calls `transaction.finish()` only after this succeeds.
 */
billing.post("/apple/verify", requireUser, rateLimit("BILLING_LIMITER", "verify"), async (c) => {
  const body = await parseJson(c, schemas.appleVerify);
  const user = c.var.user;
  let tx: apple.AppleTransaction;
  try {
    tx = await apple.verifySignedData<apple.AppleTransaction>(body.signed_transaction);
    apple.checkTransaction(c.env, tx);
  } catch (e) {
    if (e instanceof apple.AppleVerificationError || e instanceof play.InvalidPurchase) {
      console.warn("Apple verification rejected", (e as Error).message);
      throw new ApiError(400, "Satın alma doğrulanamadı.");
    }
    throw e;
  }
  // The app sets appAccountToken to the user id; refuse someone else's purchase.
  if (tx.appAccountToken && tx.appAccountToken.toLowerCase() !== user.id.toLowerCase()) {
    throw new ApiError(409, OTHER_ACCOUNT);
  }
  const owner = await c.env.DB.prepare("SELECT id FROM users WHERE apple_original_transaction_id = ?")
    .bind(tx.originalTransactionId)
    .first<{ id: string }>();
  if (owner && owner.id !== user.id) throw new ApiError(409, OTHER_ACCOUNT);

  // Prefer the freshest status from Apple when the Server API key is configured.
  let latest: { tx: apple.AppleTransaction; renewal: apple.AppleRenewalInfo | null } = { tx, renewal: null };
  if (apple.serverApiConfigured(c.env)) {
    try {
      latest = (await apple.fetchLatestStatus(c.env, tx.originalTransactionId)) ?? latest;
    } catch (e) {
      console.warn("App Store Server API status lookup failed; using the signed transaction", (e as Error).message);
    }
  }
  const fresh = await apple.applyAppleTransaction(c.env, user, latest.tx, latest.renewal);
  return c.json(await profileResponse(c.env, fresh));
});

/**
 * App Store Server Notifications V2.
 * URL (App Store Connect → App Information): https://api.synapcart.emreaydin.dev/api/v1/billing/apple/notifications
 * A non-2xx response makes Apple retry.
 */
billing.post("/apple/notifications", async (c) => {
  const body = await parseJson(c, schemas.appleNotification);
  let n: apple.AppleNotification;
  try {
    n = await apple.verifySignedData<apple.AppleNotification>(body.signedPayload);
  } catch (e) {
    console.warn("Rejected App Store notification", (e as Error).message);
    throw new ApiError(400, "Invalid notification");
  }
  const s = settings(c.env);
  if (n.data?.bundleId && n.data.bundleId !== s.appleBundleId) return c.body(null, 200);
  if (n.notificationType === "TEST" || !n.data?.signedTransactionInfo) return c.body(null, 200);

  let tx: apple.AppleTransaction;
  let renewal: apple.AppleRenewalInfo | null = null;
  try {
    tx = await apple.verifySignedData<apple.AppleTransaction>(n.data.signedTransactionInfo);
    if (n.data.signedRenewalInfo) renewal = await apple.verifySignedData<apple.AppleRenewalInfo>(n.data.signedRenewalInfo);
  } catch (e) {
    console.warn("Rejected App Store notification transaction", (e as Error).message);
    throw new ApiError(400, "Invalid notification");
  }
  if (!s.appleProductIds.includes(tx.productId)) return c.body(null, 200);

  const user = await apple.findUserForTransaction(c.env, tx);
  if (!user) {
    // Not verified by the app yet; /apple/verify will pick it up.
    console.log(`App Store notification for unknown transaction (type=${n.notificationType})`);
    return c.body(null, 200);
  }
  if (n.notificationType === "REFUND" || n.notificationType === "REVOKE") {
    tx = { ...tx, revocationDate: tx.revocationDate ?? Date.now() };
  }
  await apple.applyAppleTransaction(c.env, user, tx, renewal);
  return c.body(null, 200);
});

export default billing;
