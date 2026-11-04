import { CompactSign, importPKCS8 } from "jose";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import leafKeyPem from "./fixtures/apple/leaf.key?raw";
import leafPem from "./fixtures/apple/leaf.pem?raw";
import intPem from "./fixtures/apple/int.pem?raw";
import rootPem from "./fixtures/apple/root.pem?raw";
import { appleTrust, appleEntitlement, verifySignedData, AppleVerificationError } from "../src/services/appleBilling";
import { api, env, json, registerAndLogin, userIdFor } from "./helpers";

// Test chain generated with openssl (test/fixtures/apple): root -> intermediate (Apple WWDR marker
// OID 1.2.840.113635.100.6.2.1) -> leaf (App Store marker OID 1.2.840.113635.100.6.11.1).
const TEST_ROOT_FINGERPRINT = "A38BD34628C45275D0CAEB5BAA865E03BD12240E003BDA1A8A3509215E5B7B68";
const der = (pem: string) => pem.replace(/-----[^-]+-----/g, "").replace(/\s/g, "");
const X5C = [der(leafPem), der(intPem), der(rootPem)];

async function sign(payload: object, x5c: string[] = X5C): Promise<string> {
  const key = await importPKCS8(leafKeyPem, "ES256");
  return new CompactSign(new TextEncoder().encode(JSON.stringify(payload)))
    .setProtectedHeader({ alg: "ES256", x5c })
    .sign(key);
}

const DAY = 86_400_000;
function transaction(overrides: object = {}) {
  return {
    transactionId: "2000000001",
    originalTransactionId: "1000000001",
    bundleId: "com.neilb.synapcart",
    productId: "synapcart_premium_monthly",
    purchaseDate: Date.now() - DAY,
    expiresDate: Date.now() + 30 * DAY,
    type: "Auto-Renewable Subscription",
    environment: "Sandbox",
    signedDate: Date.now(),
    ...overrides,
  };
}

const verify = (headers: Record<string, string>, signed_transaction: string) =>
  api("/billing/apple/verify", { method: "POST", json: { signed_transaction }, headers });

const notify = async (notificationType: string, tx: object, extra: object = {}) =>
  api("/billing/apple/notifications", {
    method: "POST",
    json: {
      signedPayload: await sign({
        notificationType,
        notificationUUID: crypto.randomUUID(),
        signedDate: Date.now(),
        data: { bundleId: "com.neilb.synapcart", environment: "Sandbox", signedTransactionInfo: await sign(tx), ...extra },
      }),
    },
  });

const original = [...appleTrust.rootFingerprints];
beforeAll(() => {
  appleTrust.rootFingerprints = [TEST_ROOT_FINGERPRINT];
});
afterAll(() => {
  appleTrust.rootFingerprints = original;
});

describe("apple JWS verification", () => {
  it("accepts data signed through a trusted chain", async () => {
    const tx = transaction();
    expect(await verifySignedData(await sign(tx))).toEqual(tx);
  });

  it("rejects an untrusted root", async () => {
    appleTrust.rootFingerprints = original; // the real Apple root only
    try {
      await expect(verifySignedData(await sign(transaction()))).rejects.toThrow("Untrusted root certificate");
    } finally {
      appleTrust.rootFingerprints = [TEST_ROOT_FINGERPRINT];
    }
  });

  it("rejects a chain missing Apple's marker extensions", async () => {
    // Root used as intermediate: chain shape is fine but the marker OID is missing.
    await expect(verifySignedData(await sign(transaction(), [X5C[0], X5C[2], X5C[2]]))).rejects.toBeInstanceOf(
      AppleVerificationError,
    );
  });

  it("rejects a tampered payload", async () => {
    const jws = await sign(transaction());
    const [h, , s] = jws.split(".");
    const forged = btoa(JSON.stringify(transaction({ expiresDate: Date.now() + 999 * DAY })))
      .replace(/=+$/, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    await expect(verifySignedData(`${h}.${forged}.${s}`)).rejects.toThrow("Invalid JWS signature");
  });

  it("extends entitlement through a grace period and ends it on revocation", () => {
    const expired = transaction({ expiresDate: Date.now() - DAY });
    expect(appleEntitlement(expired)[1]).toBe(false);
    expect(appleEntitlement(expired, { gracePeriodExpiresDate: Date.now() + DAY })[1]).toBe(true);
    expect(appleEntitlement(transaction({ revocationDate: Date.now() }))[1]).toBe(false);
  });
});

describe("app store billing", () => {
  it("activates premium from a signed transaction", async () => {
    const headers = await registerAndLogin();
    const r = await verify(headers, await sign(transaction({ appAccountToken: await userIdFor() })));
    expect(r.status).toBe(200);
    const body = await json(r);
    expect(body).toMatchObject({ plan: "premium", plan_source: "apple", daily_limit: 100 });
    expect(body.plan_expires_at).toBeTruthy();
    const row = await env.DB.prepare("SELECT apple_original_transaction_id, apple_product_id FROM users").first<any>();
    expect(row).toEqual({ apple_original_transaction_id: "1000000001", apple_product_id: "synapcart_premium_monthly" });
  });

  it("rejects wrong products, bundles and forged data", async () => {
    const headers = await registerAndLogin();
    expect((await verify(headers, await sign(transaction({ productId: "other" })))).status).toBe(400);
    expect((await verify(headers, await sign(transaction({ bundleId: "com.evil.app" })))).status).toBe(400);
    expect((await verify(headers, "not-a-jws")).status).toBe(400);
    expect((await json(await api("/user/me", { headers }))).plan).toBe("free");
  });

  it("rejects Sandbox transactions in production", async () => {
    const headers = await registerAndLogin();
    const r = await api(
      "/billing/apple/verify",
      { method: "POST", json: { signed_transaction: await sign(transaction()) }, headers },
      { APPLE_ENVIRONMENT: "Production" },
    );
    expect(r.status).toBe(400);
  });

  it("refuses another account's purchase", async () => {
    const alice = await registerAndLogin("alice@example.com");
    const bob = await registerAndLogin("bob@example.com");
    const aliceId = await userIdFor("alice@example.com");
    expect((await verify(bob, await sign(transaction({ appAccountToken: aliceId })))).status).toBe(409);
    expect((await verify(alice, await sign(transaction({ appAccountToken: aliceId })))).status).toBe(200);
    // Without appAccountToken, the original transaction stays bound to its first owner.
    expect((await verify(bob, await sign(transaction()))).status).toBe(409);
  });

  it("keeps an expired transaction on free", async () => {
    const headers = await registerAndLogin();
    const r = await verify(headers, await sign(transaction({ expiresDate: Date.now() - DAY })));
    expect((await json(r)).plan).toBe("free");
  });

  it("follows App Store Server Notifications", async () => {
    const headers = await registerAndLogin();
    const userId = await userIdFor();
    const me = async () => json(await api("/user/me", { headers }));

    // A notification can arrive before the app verified: matched by appAccountToken.
    expect((await notify("SUBSCRIBED", transaction({ appAccountToken: userId }), { status: 1 })).status).toBe(200);
    expect((await me()).plan).toBe("premium");

    // Expired, then renewed (matched by originalTransactionId, no token needed).
    expect((await notify("EXPIRED", transaction({ expiresDate: Date.now() - DAY }), { status: 2 })).status).toBe(200);
    expect((await me()).plan).toBe("free");
    const renewed = Date.now() + 60 * DAY;
    expect((await notify("DID_RENEW", transaction({ expiresDate: renewed }), { status: 1 })).status).toBe(200);
    expect((await me()).plan_expires_at).toBe(new Date(renewed).toISOString());

    // Refund revokes immediately.
    expect((await notify("REFUND", transaction({ expiresDate: renewed }))).status).toBe(200);
    expect((await me()).plan).toBe("free");

    // TEST, other apps and unknown transactions are acknowledged without changes.
    const test = await api("/billing/apple/notifications", {
      method: "POST",
      json: { signedPayload: await sign({ notificationType: "TEST", signedDate: Date.now(), data: { bundleId: "com.neilb.synapcart" } }) },
    });
    expect(test.status).toBe(200);
    expect((await notify("SUBSCRIBED", transaction({ originalTransactionId: "999", appAccountToken: crypto.randomUUID() }))).status).toBe(200);
    expect((await me()).plan).toBe("free");
  });

  it("rejects unsigned notifications", async () => {
    const r = await api("/billing/apple/notifications", { method: "POST", json: { signedPayload: "a.b.c" } });
    expect(r.status).toBe(400);
  });

  it("does not let an expired App Store subscription downgrade active Play premium", async () => {
    const headers = await registerAndLogin();
    await env.DB.prepare("UPDATE users SET plan = 'premium', plan_source = 'google', plan_expires_at = ?")
      .bind(new Date(Date.now() + 10 * DAY).toISOString())
      .run();
    const r = await verify(headers, await sign(transaction({ expiresDate: Date.now() - DAY })));
    expect((await json(r)).plan).toBe("premium");
  });
});
