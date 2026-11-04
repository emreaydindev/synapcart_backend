/**
 * App Store (StoreKit 2) subscriptions.
 *
 * - The iOS app sends the signed transaction (JWS) of a purchase to
 *   POST /billing/apple/verify. `verifySignedData` checks the x5c chain up to
 *   Apple Root CA G3 (SHA-256 fingerprint pinned below), the Apple marker OIDs on
 *   the intermediate and leaf certificates, and the ES256 signature.
 * - App Store Server Notifications V2 (POST /billing/apple/notifications) are
 *   verified the same way and keep the plan in sync (renewals, expiry, refunds).
 * - The optional App Store Server API client refreshes statuses from the daily cron.
 */
import { X509Certificate, createHash } from "node:crypto";
import { SignJWT, compactVerify, decodeProtectedHeader, importPKCS8, importX509 } from "jose";
import type { Env } from "../env";
import type { UserRow } from "../db";
import { getUserById, updateUser } from "../db";
import { settings } from "../config";
import { b64Decode } from "../lib/crypto";
import { PLAN_FREE, PLAN_PREMIUM, isPremium } from "./plan";
import { BillingError, BillingNotConfigured, InvalidPurchase } from "./playBilling";

/** SHA-256 of Apple Root CA - G3 (https://www.apple.com/certificateauthority/). Tests replace it. */
export const appleTrust = {
  rootFingerprints: ["63343ABFB89A6A03EBB57E9B3F5FA7BE7C4F5C756F3017B3A8C488C3653E9179"],
};

// Marker extensions Apple puts on its WWDR intermediate and App Store signing leaf.
const OID_INTERMEDIATE = Uint8Array.from([0x06, 0x0a, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x63, 0x64, 0x06, 0x02, 0x01]);
const OID_LEAF = Uint8Array.from([0x06, 0x0a, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x63, 0x64, 0x06, 0x0b, 0x01]);

export class AppleVerificationError extends Error {}

export interface AppleTransaction {
  transactionId: string;
  originalTransactionId: string;
  bundleId: string;
  productId: string;
  purchaseDate?: number;
  expiresDate?: number;
  type?: string;
  appAccountToken?: string;
  environment?: string;
  revocationDate?: number;
  revocationReason?: number;
  signedDate?: number;
}

export interface AppleRenewalInfo {
  originalTransactionId?: string;
  autoRenewStatus?: number;
  gracePeriodExpiresDate?: number;
  isInBillingRetryPeriod?: boolean;
  productId?: string;
}

export interface AppleNotification {
  notificationType: string;
  subtype?: string;
  notificationUUID?: string;
  signedDate?: number;
  data?: {
    appAppleId?: number;
    bundleId?: string;
    environment?: string;
    signedTransactionInfo?: string;
    signedRenewalInfo?: string;
    status?: number;
  };
}

function contains(haystack: Uint8Array, needle: Uint8Array): boolean {
  outer: for (let i = 0; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (haystack[i + j] !== needle[j]) continue outer;
    return true;
  }
  return false;
}

const pem = (b64: string) => `-----BEGIN CERTIFICATE-----\n${b64.match(/.{1,64}/g)?.join("\n")}\n-----END CERTIFICATE-----`;

function decodePayloadUnverified(jws: string): Record<string, unknown> {
  const part = jws.split(".")[1];
  if (!part) throw new AppleVerificationError("Malformed JWS");
  try {
    return JSON.parse(new TextDecoder().decode(b64Decode(part)));
  } catch {
    throw new AppleVerificationError("Malformed JWS payload");
  }
}

/** Verifies an Apple-signed JWS (transaction, renewal info or notification) and returns its payload. */
export async function verifySignedData<T>(jws: string): Promise<T> {
  let header: { alg?: string; x5c?: string[] };
  try {
    header = decodeProtectedHeader(jws) as typeof header;
  } catch {
    throw new AppleVerificationError("Malformed JWS header");
  }
  if (header.alg !== "ES256" || !Array.isArray(header.x5c) || header.x5c.length !== 3) {
    throw new AppleVerificationError("Unexpected JWS header");
  }
  let certs: X509Certificate[];
  try {
    certs = header.x5c.map((c) => new X509Certificate(pem(c)));
  } catch {
    throw new AppleVerificationError("Invalid certificate in x5c");
  }
  const [leaf, intermediate, root] = certs;

  const fingerprint = createHash("sha256").update(root.raw).digest("hex").toUpperCase();
  if (!appleTrust.rootFingerprints.includes(fingerprint)) throw new AppleVerificationError("Untrusted root certificate");
  if (!contains(new Uint8Array(intermediate.raw), OID_INTERMEDIATE) || !contains(new Uint8Array(leaf.raw), OID_LEAF)) {
    throw new AppleVerificationError("Missing Apple certificate markers");
  }
  if (!leaf.verify(intermediate.publicKey) || !intermediate.verify(root.publicKey) || !root.verify(root.publicKey)) {
    throw new AppleVerificationError("Broken certificate chain");
  }
  // Like Apple's own library, check validity at the time the data was signed.
  const signedDate = Number(decodePayloadUnverified(jws).signedDate) || Date.now();
  for (const cert of certs) {
    if (signedDate < Date.parse(cert.validFrom) || signedDate > Date.parse(cert.validTo)) {
      throw new AppleVerificationError("Certificate not valid at signing time");
    }
  }

  try {
    const key = await importX509(pem(header.x5c[0]), "ES256");
    const { payload } = await compactVerify(jws, key);
    return JSON.parse(new TextDecoder().decode(payload)) as T;
  } catch {
    throw new AppleVerificationError("Invalid JWS signature");
  }
}

/** Checks the transaction belongs to this app, product and environment. */
export function checkTransaction(env: Env, tx: AppleTransaction): void {
  const s = settings(env);
  if (tx.bundleId !== s.appleBundleId) throw new InvalidPurchase("bundle");
  if (!s.appleProductIds.includes(tx.productId)) throw new InvalidPurchase("product");
  // Production accepts only Production; staging/dev (Sandbox) also accepts Xcode and TestFlight sandbox data.
  if (s.appleEnvironment === "Production" && tx.environment && tx.environment !== "Production") {
    throw new InvalidPurchase("environment");
  }
}

/** [expiryIso, entitled] for a transaction (optionally extended by a grace period). */
export function appleEntitlement(tx: AppleTransaction, renewal?: AppleRenewalInfo | null, now = Date.now()): [string | null, boolean] {
  if (tx.revocationDate) return [null, false];
  let expiry = tx.expiresDate ?? null;
  if (renewal?.gracePeriodExpiresDate && (expiry === null || renewal.gracePeriodExpiresDate > expiry)) {
    expiry = renewal.gracePeriodExpiresDate;
  }
  if (expiry === null) return [null, false];
  return [new Date(expiry).toISOString(), expiry > now];
}

export async function applyAppleTransaction(env: Env, user: UserRow, tx: AppleTransaction, renewal?: AppleRenewalInfo | null) {
  const [expiry, entitled] = appleEntitlement(tx, renewal);
  const ids = { apple_original_transaction_id: tx.originalTransactionId, apple_product_id: tx.productId };
  // An inactive App Store subscription never downgrades an active Play one.
  if (!entitled && user.plan_source === "google" && isPremium(user)) return updateUser(env.DB, user.id, ids);
  const fresh = await updateUser(env.DB, user.id, {
    ...ids,
    plan: entitled ? PLAN_PREMIUM : PLAN_FREE,
    plan_expires_at: entitled ? expiry : null,
    plan_source: "apple",
  });
  console.log(`Plan updated from App Store (user=${user.id}, entitled=${entitled})`);
  return fresh;
}

export async function findUserForTransaction(env: Env, tx: AppleTransaction): Promise<UserRow | null> {
  const byOriginal = await env.DB.prepare("SELECT * FROM users WHERE apple_original_transaction_id = ?")
    .bind(tx.originalTransactionId)
    .first<UserRow>();
  if (byOriginal) return byOriginal;
  // The app sets appAccountToken to the user id (a UUID) at purchase time.
  return tx.appAccountToken ? getUserById(env.DB, tx.appAccountToken.toLowerCase()) : null;
}

// --- App Store Server API (optional) ---

const API_HOST = { Production: "https://api.storekit.itunes.apple.com", Sandbox: "https://api.storekit-sandbox.itunes.apple.com" };

export function serverApiConfigured(env: Env): boolean {
  return !!(env.APPLE_ISSUER_ID && env.APPLE_KEY_ID && env.APPLE_PRIVATE_KEY);
}

async function serverApiToken(env: Env): Promise<string> {
  if (!serverApiConfigured(env)) throw new BillingNotConfigured();
  const key = await importPKCS8(env.APPLE_PRIVATE_KEY!.replace(/\\n/g, "\n"), "ES256");
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({ bid: settings(env).appleBundleId })
    .setProtectedHeader({ alg: "ES256", kid: env.APPLE_KEY_ID!, typ: "JWT" })
    .setIssuer(env.APPLE_ISSUER_ID!)
    .setAudience("appstoreconnect-v1")
    .setIssuedAt(now)
    .setExpirationTime(now + 1200)
    .sign(key);
}

/**
 * Latest signed transaction + renewal info for a subscription
 * (GET /inApps/v1/subscriptions/{originalTransactionId}).
 */
export async function fetchLatestStatus(
  env: Env,
  originalTransactionId: string,
): Promise<{ tx: AppleTransaction; renewal: AppleRenewalInfo | null } | null> {
  const token = await serverApiToken(env);
  const host = API_HOST[settings(env).appleEnvironment];
  let res: Response;
  try {
    res = await fetch(`${host}/inApps/v1/subscriptions/${encodeURIComponent(originalTransactionId)}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(15_000),
    });
  } catch (e) {
    throw new BillingError(`App Store Server API request failed: ${(e as Error).name}`);
  }
  if (res.status === 404) return null;
  if (!res.ok) throw new BillingError(`App Store Server API returned ${res.status}`);
  const body = (await res.json()) as {
    data?: { lastTransactions?: { signedTransactionInfo?: string; signedRenewalInfo?: string }[] }[];
  };
  const last = body.data?.flatMap((g) => g.lastTransactions ?? []) ?? [];
  let best: { tx: AppleTransaction; renewal: AppleRenewalInfo | null } | null = null;
  for (const item of last) {
    if (!item.signedTransactionInfo) continue;
    const tx = await verifySignedData<AppleTransaction>(item.signedTransactionInfo);
    const renewal = item.signedRenewalInfo ? await verifySignedData<AppleRenewalInfo>(item.signedRenewalInfo) : null;
    if (!best || (tx.expiresDate ?? 0) > (best.tx.expiresDate ?? 0)) best = { tx, renewal };
  }
  return best;
}
