import { createExecutionContext, env } from "cloudflare:test";
import { expect, vi } from "vitest";
import { app } from "../src/app";
import { defaultDeps } from "../src/services/agent";
import { SearchError, type Product } from "../src/services/search";

export { env };

type Init = { method?: string; json?: unknown; body?: BodyInit; headers?: Record<string, string> };

/** Calls the app in-process. `overrides` replaces env vars/secrets for this request. */
export async function api(path: string, init: Init = {}, overrides: Partial<typeof env> = {}) {
  const headers: Record<string, string> = { ...(init.headers ?? {}) };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await app.request(`/api/v1${path}`, { method: init.method ?? "GET", headers, body }, { ...env, ...overrides }, createExecutionContext());
  return res;
}

export async function json<T = any>(res: Response): Promise<T> {
  return (await res.json()) as T;
}

export async function registerAndLogin(email = "user@example.com", password = "secret123", name = "Ada") {
  let r = await api("/auth/register", { method: "POST", json: { email, password, name } });
  expect(r.status, await r.clone().text()).toBe(201);
  r = await api("/auth/login", { method: "POST", json: { email, password } });
  expect(r.status).toBe(200);
  const token = (await json(r)).access_token as string;
  return { Authorization: `Bearer ${token}` };
}

export async function userIdFor(email = "user@example.com"): Promise<string> {
  return (await env.DB.prepare("SELECT id FROM users WHERE email = ?").bind(email).first<{ id: string }>())!.id;
}

export async function setPremium(email = "user@example.com", expiresAt: string | null = null) {
  await env.DB.prepare("UPDATE users SET plan = 'premium', plan_expires_at = ? WHERE email = ?").bind(expiresAt, email).run();
}

/** Deterministic stand-ins for Gemini and SerpAPI in the agent. */
export function fakeAI() {
  const fake = {
    shopping: true,
    failSearch: false,
    products: [
      { title: "Phone A", price: 100, source: "Shop", link: "https://a.example", thumbnail: null },
      { title: "Phone B", price: 200, source: "Shop", link: "https://b.example", thumbnail: null },
    ] as Product[],
    calls: [] as [string, string, unknown][],
  };
  vi.spyOn(defaultDeps, "isShoppingRelated").mockImplementation(async (_e, q, h = []) => {
    fake.calls.push(["router", q, [...h]]);
    return fake.shopping;
  });
  vi.spyOn(defaultDeps, "extractSearchQuery").mockImplementation(async (_e, q, h = []) => {
    fake.calls.push(["query", q, [...h]]);
    return "phone";
  });
  vi.spyOn(defaultDeps, "analyzeProducts").mockImplementation(async (_e, q, products, o) => {
    fake.calls.push(["analyst", q, o]);
    return `Best pick: ${products[0].title}`;
  });
  vi.spyOn(defaultDeps, "searchProducts").mockImplementation(async (_e, _q, _l, _c, limit) => {
    if (fake.failSearch) throw new SearchError("boom");
    return fake.products.slice(0, limit);
  });
  return fake;
}

type Handler = (req: Request) => Response | Promise<Response>;

/** Routes outbound fetch() by URL prefix; unknown URLs fail the test. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: Request[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = new Request(input, init);
    calls.push(req.clone());
    for (const [prefix, handler] of Object.entries(routes)) {
      if (req.url.startsWith(prefix)) return handler(req);
    }
    throw new Error(`Unexpected fetch: ${req.url}`);
  });
  return calls;
}

export const jsonResponse = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

export function parseSse(text: string): any[] {
  return text
    .split("\n\n")
    .filter((b) => b.startsWith("data: "))
    .map((b) => JSON.parse(b.slice(6)));
}

/** A throwaway Google service account (RSA key generated with WebCrypto). */
export async function serviceAccount(projectId = "synapcart-test") {
  const pair = (await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  const pkcs8 = new Uint8Array((await crypto.subtle.exportKey("pkcs8", pair.privateKey)) as ArrayBuffer);
  let bin = "";
  for (const b of pkcs8) bin += String.fromCharCode(b);
  const pem = `-----BEGIN PRIVATE KEY-----\n${btoa(bin).match(/.{1,64}/g)!.join("\n")}\n-----END PRIVATE KEY-----\n`;
  return {
    account: {
      type: "service_account",
      project_id: projectId,
      private_key_id: "kid1",
      private_key: pem,
      client_email: `bot@${projectId}.iam.gserviceaccount.com`,
      token_uri: "https://oauth2.googleapis.com/token",
    },
    publicKey: pair.publicKey,
  };
}
