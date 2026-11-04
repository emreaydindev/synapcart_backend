import { decodeJwt } from "jose";
import { describe, expect, it } from "vitest";
import { outbox, type OutgoingEmail } from "../src/services/email";
import { sha256Hex } from "../src/lib/crypto";
import { api, env, json, registerAndLogin } from "./helpers";

function captureEmails() {
  const sent: OutgoingEmail[] = [];
  outbox.capture = (m) => {
    sent.push(m);
  };
  return sent;
}

const tokenFrom = (m: OutgoingEmail) => decodeURIComponent(/token=([^\s"&]+)/.exec(m.text)![1]);
const userRow = () => env.DB.prepare("SELECT * FROM users").first<any>();
const userCount = async () => (await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first<{ n: number }>())!.n;

describe("auth", () => {
  it("validates the password on register with a readable detail", async () => {
    const r = await api("/auth/register", { method: "POST", json: { email: "a@b.com", password: "short", name: "A" } });
    expect(r.status).toBe(422);
    const body = await json(r);
    expect(typeof body.detail).toBe("string");
    expect(body.detail).toContain("8");
  });

  it("rejects digit-only and letter-only passwords", async () => {
    for (const password of ["12345678", "abcdefgh"]) {
      const r = await api("/auth/register", { method: "POST", json: { email: "a@b.com", password, name: "A" } });
      expect((await json(r)).detail).toBe("Şifre hem harf hem rakam içermelidir.");
    }
  });

  it("treats emails case-insensitively", async () => {
    await registerAndLogin("Mixed@Example.com");
    let r = await api("/auth/login", { method: "POST", json: { email: "mixed@example.COM", password: "secret123" } });
    expect(r.status).toBe(200);
    r = await api("/auth/register", { method: "POST", json: { email: "MIXED@example.com", password: "secret123", name: "B" } });
    expect(r.status).toBe(400);
  });

  it("issues a week-long token carrying the user's name", async () => {
    await registerAndLogin();
    const r = await api("/auth/login", { method: "POST", json: { email: "user@example.com", password: "secret123" } });
    const body = await json(r);
    expect(body.user_name).toBe("Ada");
    expect(body.token_type).toBe("bearer");
    const claims = decodeJwt(body.access_token);
    expect(claims.sub).toBe("user@example.com");
    expect(claims.exp! - Date.now() / 1000).toBeGreaterThan(7 * 24 * 3600 - 60);
  });

  it("returns 401 for a wrong password", async () => {
    await registerAndLogin();
    const r = await api("/auth/login", { method: "POST", json: { email: "user@example.com", password: "nope12345" } });
    expect(r.status).toBe(401);
  });

  it("resets the password, stores the token hashed and revokes old tokens", async () => {
    const headers = await registerAndLogin();
    const sent = captureEmails();
    expect((await api("/auth/forgot-password", { method: "POST", json: { email: "user@example.com" } })).status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].subject).toBe("SynapCart - Şifre Sıfırlama");
    expect(sent[0].html).toContain("https://synapcart.emreaydin.dev/reset-password?token=");
    const raw = tokenFrom(sent[0]);
    expect((await userRow()).reset_token).toBe(await sha256Hex(raw));

    let r = await api("/auth/reset-password", { method: "POST", json: { token: raw, new_password: "newpass123" } });
    expect(r.status).toBe(200);
    expect((await api("/user/me", { headers })).status).toBe(401);
    r = await api("/auth/reset-password", { method: "POST", json: { token: raw, new_password: "other1234" } });
    expect(r.status).toBe(400);
    r = await api("/auth/login", { method: "POST", json: { email: "user@example.com", password: "newpass123" } });
    expect(r.status).toBe(200);
  });

  it("does not reveal accounts when sending fails", async () => {
    await registerAndLogin();
    outbox.capture = () => {
      throw new Error("email down");
    };
    const known = await api("/auth/forgot-password", { method: "POST", json: { email: "user@example.com" } });
    const unknown = await api("/auth/forgot-password", { method: "POST", json: { email: "nobody@example.com" } });
    expect(known.status).toBe(200);
    expect(unknown.status).toBe(200);
    expect(await json(known)).toEqual(await json(unknown));
    expect((await userRow()).reset_token).toBeNull();
  });

  it("rejects an expired reset token", async () => {
    await registerAndLogin();
    await env.DB.prepare("UPDATE users SET reset_token = ?, reset_token_expires = ?")
      .bind(await sha256Hex("tok"), new Date(Date.now() - 60_000).toISOString())
      .run();
    const r = await api("/auth/reset-password", { method: "POST", json: { token: "tok", new_password: "newpass123" } });
    expect(r.status).toBe(400);
  });

  it("changes the password and deletes the account", async () => {
    const headers = await registerAndLogin();
    let r = await api("/user/me/password", {
      method: "POST",
      json: { current_password: "wrongpass1", new_password: "another123" },
      headers,
    });
    expect(r.status).toBe(403);
    r = await api("/user/me/password", { method: "POST", json: { current_password: "secret123", new_password: "another123" }, headers });
    expect(r.status).toBe(200);
    const fresh = { Authorization: `Bearer ${(await json(r)).access_token}` };
    expect((await api("/user/me", { headers })).status).toBe(401);
    expect((await api("/user/me", { headers: fresh })).status).toBe(200);

    expect((await api("/user/me", { method: "DELETE", json: { password: "bad" }, headers: fresh })).status).toBe(403);
    expect((await api("/user/me", { method: "DELETE", json: { password: "another123" }, headers: fresh })).status).toBe(204);
    expect((await api("/user/me", { headers: fresh })).status).toBe(401);
  });

  it("deletes the account without a body", async () => {
    const headers = await registerAndLogin();
    expect((await api("/user/me", { method: "DELETE", headers })).status).toBe(204);
    expect(await userCount()).toBe(0);
  });

  it("validates profile updates", async () => {
    const headers = await registerAndLogin();
    expect((await api("/user/me", { method: "PATCH", json: { language: "xx" }, headers })).status).toBe(422);
    const r = await api("/user/me", { method: "PATCH", json: { language: "EN", currency: "usd" }, headers });
    expect(r.status).toBe(200);
    const body = await json(r);
    expect(body.language).toBe("en");
    expect(body.currency).toBe("USD");
    expect(body.plan).toBe("free");
    expect(body.daily_limit).toBe(5);
  });

  it("runs the web account-deletion flow with a cooldown", async () => {
    const headers = await registerAndLogin();
    await api("/favorites/", { method: "POST", json: { title: "X", price: 10, link: "https://shop.example/x", source: "Shop" }, headers });
    const sent = captureEmails();
    const known = await api("/auth/delete-request", { method: "POST", json: { email: "USER@example.com" } });
    const unknown = await api("/auth/delete-request", { method: "POST", json: { email: "nobody@example.com" } });
    expect(await json(known)).toEqual(await json(unknown));
    expect(sent).toHaveLength(1);
    const raw = tokenFrom(sent[0]);
    expect((await userRow()).delete_token).toBe(await sha256Hex(raw));

    await api("/auth/delete-request", { method: "POST", json: { email: "user@example.com" } });
    expect(sent).toHaveLength(1); // cooldown

    expect((await api("/auth/delete-confirm", { method: "POST", json: { token: "wrong" } })).status).toBe(400);
    expect((await api("/auth/delete-confirm", { method: "POST", json: { token: raw } })).status).toBe(200);
    expect(await userCount()).toBe(0);
    const favs = await env.DB.prepare("SELECT COUNT(*) AS n FROM favorites").first<{ n: number }>();
    expect(favs!.n).toBe(0); // cascaded
    expect((await api("/user/me", { headers })).status).toBe(401);
    expect((await api("/auth/delete-confirm", { method: "POST", json: { token: raw } })).status).toBe(400);
  });

  it("expires web deletion links", async () => {
    await registerAndLogin();
    const sent = captureEmails();
    await api("/auth/delete-request", { method: "POST", json: { email: "user@example.com" } });
    await env.DB.prepare("UPDATE users SET delete_token_expires = ?").bind(new Date(Date.now() - 60_000).toISOString()).run();
    const r = await api("/auth/delete-confirm", { method: "POST", json: { token: tokenFrom(sent[0]) } });
    expect(r.status).toBe(400);
    expect(await userCount()).toBe(1);
  });

  it("serves health and CORS for allowed origins only", async () => {
    let r = await api("/health");
    expect(await json(r)).toMatchObject({ status: "ok", database: "ok" });
    r = await api("/health", { headers: { Origin: "https://synapcart.emreaydin.dev" } });
    expect(r.headers.get("access-control-allow-origin")).toBe("https://synapcart.emreaydin.dev");
    r = await api("/health", { headers: { Origin: "https://evil.example" } });
    expect(r.headers.get("access-control-allow-origin")).toBeNull();
  });
});
