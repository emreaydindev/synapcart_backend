import { jwtVerify } from "jose";
import { describe, expect, it } from "vitest";
import { runPriceCheck } from "../src/jobs/priceCheck";
import { SCOPE_FCM } from "../src/services/google";
import * as push from "../src/services/push";
import { entitlement } from "../src/services/playBilling";
import { getSerpParams } from "../src/services/search";
import { api, env, json, jsonResponse, mockFetch, registerAndLogin, serviceAccount, setPremium, userIdFor } from "./helpers";

type H = Record<string, string>;
const PRODUCTS = [
  { title: "Phone A", price: 100, source: "Shop", link: "https://a.example" },
  { title: "Phone B", price: 200, source: "Shop", link: "https://b.example" },
];
const GEMINI = "https://generativelanguage.googleapis.com/";
const geminiText = (text: string) => jsonResponse({ candidates: [{ content: { parts: [{ text }] } }] });

describe("favorites", () => {
  it("adds idempotently and parses string prices", async () => {
    const headers = await registerAndLogin();
    const body = { title: "X", price: "1.299,50", link: "https://shop.example/x", source: "Shop" };
    let r = await api("/favorites/", { method: "POST", json: body, headers });
    expect(r.status).toBe(201);
    const fav = await json(r);
    expect(fav.price).toBe(1299.5);
    expect(fav.currency).toBe("TRY");
    expect(fav.added_at).toBeTruthy();
    r = await api("/favorites", { method: "POST", json: body, headers });
    expect(r.status).toBe(200);
    expect((await json(r)).id).toBe(fav.id);
    expect(await json(await api("/favorites/", { headers }))).toHaveLength(1);
    r = await api("/favorites/", { method: "POST", json: { ...body, link: "javascript:alert(1)" }, headers });
    expect(r.status).toBe(422);
    expect((await json(r)).detail).toBe("Geçersiz ürün linki.");
  });

  it("deletes by link", async () => {
    const headers = await registerAndLogin();
    await api("/favorites/", { method: "POST", json: { title: "X", link: "https://shop.example/x" }, headers });
    const q = `?link=${encodeURIComponent("https://shop.example/x")}`;
    expect((await api(`/favorites/by-link${q}`, { method: "DELETE", headers })).status).toBe(204);
    expect((await api(`/favorites/by-link${q}`, { method: "DELETE", headers })).status).toBe(404);
  });

  it("cannot delete someone else's favorite", async () => {
    const alice = await registerAndLogin("alice@example.com");
    const bob = await registerAndLogin("bob@example.com");
    const fav = await json(await api("/favorites/", { method: "POST", json: { title: "X", link: "https://s.example/x" }, headers: alice }));
    expect((await api(`/favorites/${fav.id}`, { method: "DELETE", headers: bob })).status).toBe(404);
    expect((await api(`/favorites/${fav.id}`, { method: "DELETE", headers: alice })).status).toBe(204);
  });
});

describe("compare", () => {
  it("requires premium", async () => {
    const headers = await registerAndLogin();
    const r = await api("/chat/compare", { method: "POST", json: { products: PRODUCTS }, headers });
    expect(r.status).toBe(402);
    expect((await json(r)).code).toBe("premium_required");
  });

  it("returns one item per product in order", async () => {
    const calls = mockFetch({
      [GEMINI]: () =>
        geminiText(
          '```json\n{"items": [{"title": "A", "pros": ["cheap", "light"], "cons": ["slow"]}], "verdict": "Pick A.", "best_index": 0}\n```',
        ),
    });
    const headers = await registerAndLogin();
    await setPremium();
    expect((await api("/chat/compare", { method: "POST", json: { products: PRODUCTS.slice(0, 1) }, headers })).status).toBe(422);
    const r = await api("/chat/compare", { method: "POST", json: { products: PRODUCTS }, headers });
    expect(r.status).toBe(200);
    const body = await json(r);
    expect(body.items.map((i: any) => i.title)).toEqual(["Phone A", "Phone B"]);
    expect(body.items[0].pros).toEqual(["cheap", "light"]);
    expect(body.items[1].pros).toEqual([]);
    expect(body.items[0].link).toBe("https://a.example");
    expect(body.verdict).toBe("Pick A.");
    expect(body.best_index).toBe(0);
    const sent = await calls[0].json<any>();
    expect(calls[0].url).toContain("gemini-2.5-flash:generateContent");
    expect(sent.generationConfig.responseMimeType).toBe("application/json");
    expect(sent.contents[0].parts[0].text).toContain("Türkçe");
  });

  it("maps Gemini failures to 502", async () => {
    mockFetch({ [GEMINI]: () => jsonResponse({ error: "quota" }, 429) });
    const headers = await registerAndLogin();
    await setPremium();
    const r = await api("/chat/compare", { method: "POST", json: { products: PRODUCTS }, headers });
    expect(r.status).toBe(502);
    expect((await json(r)).detail).toBeTruthy();
  });
});

async function favorite(headers: H, extra: object = {}) {
  const body = { title: "Phone A", price: 120, source: "Shop", link: "https://a.example", ...extra };
  return json(await api("/favorites/", { method: "POST", json: body, headers }));
}

describe("price alerts", () => {
  it("makes the price target a premium feature", async () => {
    const headers = await registerAndLogin();
    const fav = await favorite(headers);
    let r = await api(`/favorites/${fav.id}`, { method: "PATCH", json: { target_price: 100 }, headers });
    expect(r.status).toBe(402);
    expect((await json(r)).code).toBe("premium_required");

    await setPremium();
    r = await api(`/favorites/${fav.id}`, { method: "PATCH", json: { target_price: 100 }, headers });
    expect(r.status).toBe(200);
    expect((await json(r)).target_price).toBe(100);
    expect((await json(await api("/favorites/", { headers })))[0].target_price).toBe(100);
    expect((await api(`/favorites/${fav.id}`, { method: "PATCH", json: { target_price: -1 }, headers })).status).toBe(422);
    r = await api(`/favorites/${fav.id}`, { method: "PATCH", json: { target_price: null }, headers });
    expect((await json(r)).target_price).toBeNull();
  });

  it("registers, moves and deletes device tokens", async () => {
    const alice = await registerAndLogin("alice@example.com");
    const bob = await registerAndLogin("bob@example.com");
    expect((await api("/user/me/device-token", { method: "POST", json: { token: "t1" }, headers: alice })).status).toBe(204);
    expect(
      (await api("/user/me/device-token", { method: "POST", json: { token: "t1", platform: "ios" }, headers: bob })).status,
    ).toBe(204);
    const { results } = await env.DB.prepare("SELECT * FROM device_tokens").all<any>();
    expect(results).toHaveLength(1);
    expect(results[0].user_id).toBe(await userIdFor("bob@example.com"));
    expect(results[0].platform).toBe("ios");
    expect((await api("/user/me/device-token", { method: "DELETE", json: { token: "t1" }, headers: bob })).status).toBe(204);
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM device_tokens").first<any>()).n).toBe(0);
  });

  it("runs the daily price check and notifies once per drop", async () => {
    const { account } = await serviceAccount();
    const jobEnv = { ...env, FIREBASE_SERVICE_ACCOUNT_JSON: JSON.stringify(account) };
    const headers = await registerAndLogin();
    await setPremium();
    const fav = await favorite(headers);
    await api(`/favorites/${fav.id}`, { method: "PATCH", json: { target_price: 100 }, headers });
    await api("/user/me/device-token", { method: "POST", json: { token: "dev-1" }, headers });

    let price = 95;
    const sent: any[] = [];
    mockFetch({
      "https://serpapi.com/": (req) => {
        expect(new URL(req.url).searchParams.get("q")).toBe("Phone A");
        return jsonResponse({
          shopping_results: [
            { title: "Other", extracted_price: 10, source: "X", link: "https://other.example" },
            { title: "Phone A", extracted_price: price, source: "Shop", link: "https://a.example" },
          ],
        });
      },
      "https://oauth2.googleapis.com/": () => jsonResponse({ access_token: "at", expires_in: 3600 }),
      "https://fcm.googleapis.com/": async (req) => {
        sent.push((await req.json<any>()).message);
        return jsonResponse({ name: "m/1" });
      },
    });

    expect((await runPriceCheck(jobEnv)).notified).toBe(1);
    expect(sent[0].token).toBe("dev-1");
    expect(sent[0].notification.title).toBe("Fiyat düştü!");
    expect(sent[0].data).toMatchObject({ type: "price_alert", link: "https://a.example", favorite_id: String(fav.id) });
    expect(sent[0].apns.payload.aps.sound).toBe("default");
    expect((await runPriceCheck(jobEnv)).notified).toBe(0); // same price
    price = 90;
    expect((await runPriceCheck(jobEnv)).notified).toBe(1);
    price = 150;
    expect((await runPriceCheck(jobEnv)).notified).toBe(0);
    expect((await json(await api("/favorites/", { headers })))[0].last_checked_price).toBe(150);

    await setPremium("user@example.com", new Date(Date.now() - 86_400_000).toISOString());
    expect((await runPriceCheck(jobEnv)).checked).toBe(0);
  });

  it("drops unregistered tokens and doesn't mark the alert as sent", async () => {
    const { account } = await serviceAccount();
    const jobEnv = { ...env, FIREBASE_SERVICE_ACCOUNT_JSON: JSON.stringify(account) };
    const headers = await registerAndLogin();
    await setPremium();
    const fav = await favorite(headers);
    await api(`/favorites/${fav.id}`, { method: "PATCH", json: { target_price: 200 }, headers });
    await api("/user/me/device-token", { method: "POST", json: { token: "dead" }, headers });
    mockFetch({
      "https://serpapi.com/": () =>
        jsonResponse({ shopping_results: [{ title: "Phone A", extracted_price: 120, source: "Shop", link: "https://a.example" }] }),
      "https://oauth2.googleapis.com/": () => jsonResponse({ access_token: "at", expires_in: 3600 }),
      "https://fcm.googleapis.com/": () => jsonResponse({ error: { details: [{ errorCode: "UNREGISTERED" }] } }, 404),
    });
    expect((await runPriceCheck(jobEnv)).notified).toBe(0);
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM device_tokens").first<any>()).n).toBe(0);
    const row = await env.DB.prepare("SELECT last_notified_price FROM favorites WHERE id = ?").bind(fav.id).first<any>();
    expect(row.last_notified_price).toBeNull();
  });
});

describe("google service accounts and FCM", () => {
  it("exchanges a signed assertion once and sends two messages", async () => {
    const { account, publicKey } = await serviceAccount();
    const pushEnv = { ...env, FIREBASE_SERVICE_ACCOUNT_JSON: JSON.stringify(account) };
    const calls = mockFetch({
      "https://oauth2.googleapis.com/": async (req) => {
        const form = new URLSearchParams(await req.text());
        const { payload } = await jwtVerify(form.get("assertion")!, publicKey, { audience: account.token_uri });
        expect(payload.iss).toBe(account.client_email);
        expect(payload.scope).toBe(SCOPE_FCM);
        return jsonResponse({ access_token: "at-1", expires_in: 3600 });
      },
      "https://fcm.googleapis.com/": (req) => {
        expect(req.headers.get("authorization")).toBe("Bearer at-1");
        return jsonResponse({ name: "projects/synapcart-test/messages/1" });
      },
    });
    expect(push.isConfigured(pushEnv)).toBe(true);
    await push.send(pushEnv, "device", "Title", "Body", { favorite_id: "3" });
    await push.send(pushEnv, "device", "Title", "Body");
    expect(calls.map((r) => new URL(r.url).host)).toEqual(["oauth2.googleapis.com", "fcm.googleapis.com", "fcm.googleapis.com"]);
    expect(new URL(calls[1].url).pathname).toBe("/v1/projects/synapcart-test/messages:send");
    const message = (await calls[1].json<any>()).message;
    expect(message.token).toBe("device");
    expect(message.data).toEqual({ favorite_id: "3" });
    expect(message.android.notification.channel_id).toBe("price_alerts");
  });

  it("raises InvalidToken for unregistered devices", async () => {
    const { account } = await serviceAccount();
    const pushEnv = { ...env, FIREBASE_SERVICE_ACCOUNT_JSON: JSON.stringify(account) };
    mockFetch({
      "https://oauth2.googleapis.com/": () => jsonResponse({ access_token: "at", expires_in: 3600 }),
      "https://fcm.googleapis.com/": () => jsonResponse({ error: { status: "NOT_FOUND" } }, 404),
    });
    await expect(push.send(pushEnv, "gone", "t", "b")).rejects.toBeInstanceOf(push.InvalidToken);
  });

  it("reports push as not configured without a key", () => {
    expect(push.isConfigured({ ...env, FIREBASE_SERVICE_ACCOUNT_JSON: "" })).toBe(false);
  });
});

describe("search params", () => {
  it("maps currency to the shopping country", () => {
    expect(getSerpParams("x", "en", "TRY")).toMatchObject({ gl: "tr", location: "Turkey", hl: "en" });
    expect(getSerpParams("x", "tr", "EUR")).toMatchObject({ gl: "de" });
    expect(getSerpParams("x", "de", "EUR")).toMatchObject({ gl: "de", hl: "de" });
    expect(getSerpParams("x", "tr", "GBP")).toMatchObject({ gl: "uk" });
  });
});

// --- Google Play billing ---

const TOKEN_OK = "play-token-1";
const subscription = (state = "SUBSCRIPTION_STATE_ACTIVE", days = 30, product = "synapcart_premium", account?: string) => ({
  subscriptionState: state,
  lineItems: [{ productId: product, expiryTime: new Date(Date.now() + days * 86_400_000).toISOString() }],
  ...(account ? { externalAccountIdentifiers: { obfuscatedExternalAccountId: account } } : {}),
});

async function playEnv() {
  const { account } = await serviceAccount();
  const subs: Record<string, object> = {};
  mockFetch({
    "https://oauth2.googleapis.com/": () => jsonResponse({ access_token: "at", expires_in: 3600 }),
    "https://androidpublisher.googleapis.com/": (req) => {
      const token = decodeURIComponent(req.url.split("/tokens/")[1]);
      return subs[token] ? jsonResponse(subs[token]) : jsonResponse({ error: "not found" }, 404);
    },
  });
  return { subs, overrides: { GOOGLE_PLAY_SERVICE_ACCOUNT_JSON: JSON.stringify(account), PLAY_RTDN_TOKEN: "rtdn-secret" } };
}

describe("google play billing", () => {
  const verify = (headers: H, overrides: object, token = TOKEN_OK, product = "synapcart_premium") =>
    api("/billing/google/verify", { method: "POST", json: { purchase_token: token, product_id: product }, headers }, overrides);

  it("activates premium", async () => {
    const { subs, overrides } = await playEnv();
    const headers = await registerAndLogin();
    subs[TOKEN_OK] = subscription(undefined, undefined, undefined, await userIdFor());
    const r = await verify(headers, overrides);
    expect(r.status).toBe(200);
    const body = await json(r);
    expect(body.plan).toBe("premium");
    expect(body.plan_expires_at).toBeTruthy();
    expect(body.plan_source).toBe("google");
    expect((await json(await api("/user/me", { headers }))).daily_limit).toBe(100);
    expect((await verify(headers, overrides, TOKEN_OK, "other")).status).toBe(400);
    expect((await verify(headers, overrides, "unknown")).status).toBe(400);
  });

  it("rejects another account's purchase", async () => {
    const { subs, overrides } = await playEnv();
    const alice = await registerAndLogin("alice@example.com");
    const bob = await registerAndLogin("bob@example.com");
    subs[TOKEN_OK] = subscription(undefined, undefined, undefined, await userIdFor("alice@example.com"));
    expect((await verify(bob, overrides)).status).toBe(409);
    expect((await verify(alice, overrides)).status).toBe(200);
    subs[TOKEN_OK] = subscription();
    expect((await verify(bob, overrides)).status).toBe(409);
  });

  it("keeps an expired subscription on free", async () => {
    const { subs, overrides } = await playEnv();
    const headers = await registerAndLogin();
    subs[TOKEN_OK] = subscription("SUBSCRIPTION_STATE_EXPIRED", -1);
    expect((await json(await verify(headers, overrides))).plan).toBe("free");
  });

  it("returns 503 when not configured", async () => {
    const headers = await registerAndLogin();
    expect((await verify(headers, { GOOGLE_PLAY_SERVICE_ACCOUNT_JSON: "" })).status).toBe(503);
  });

  it("updates the plan from RTDN", async () => {
    const { subs, overrides } = await playEnv();
    const headers = await registerAndLogin();
    subs[TOKEN_OK] = subscription();
    await verify(headers, overrides);
    const rtdn = (payload: object, token = "rtdn-secret") =>
      api(
        `/billing/google/rtdn?token=${token}`,
        { method: "POST", json: { message: { data: btoa(JSON.stringify(payload)), messageId: "1" }, subscription: "s" } },
        overrides,
      );
    const note = {
      packageName: "com.neilb.synapcart",
      subscriptionNotification: { notificationType: 13, purchaseToken: TOKEN_OK, subscriptionId: "synapcart_premium" },
    };
    expect((await rtdn(note, "wrong")).status).toBe(403);

    subs[TOKEN_OK] = subscription("SUBSCRIPTION_STATE_EXPIRED", -1);
    expect((await rtdn(note)).status).toBe(204);
    expect((await json(await api("/user/me", { headers }))).plan).toBe("free");

    subs["play-token-2"] = { ...subscription(), linkedPurchaseToken: TOKEN_OK };
    note.subscriptionNotification.purchaseToken = "play-token-2";
    expect((await rtdn(note)).status).toBe(204);
    expect((await json(await api("/user/me", { headers }))).plan).toBe("premium");

    expect((await rtdn({ voidedPurchaseNotification: { purchaseToken: "play-token-2" } })).status).toBe(204);
    expect((await json(await api("/user/me", { headers }))).plan).toBe("free");
    expect((await rtdn({ testNotification: { version: "1.0" } })).status).toBe(204);
  });

  it("entitles cancelled subscriptions until expiry only", () => {
    const [, expiry, entitled] = entitlement(env, subscription("SUBSCRIPTION_STATE_CANCELED", 3));
    expect(entitled).toBe(true);
    expect(new Date(expiry!).getTime()).toBeGreaterThan(Date.now());
    expect(entitlement(env, subscription("SUBSCRIPTION_STATE_ON_HOLD"))[2]).toBe(false);
    expect(entitlement(env, subscription(undefined, undefined, "unknown"))[2]).toBe(false);
  });
});
