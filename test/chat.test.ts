import { describe, expect, it } from "vitest";
import { DEFAULT_MODEL } from "../src/services/gemini";
import { api, fakeAI, json, parseSse, registerAndLogin, setPremium } from "./helpers";

type H = Record<string, string>;
const newSession = async (headers: H) => (await json(await api("/chat/sessions", { method: "POST", headers }))).id as number;
const ask = (headers: H, sid: number, message = "phone") => api(`/chat/agent/${sid}`, { method: "POST", json: { message }, headers });
const stream = (headers: H, sid: number, message: string) =>
  api(`/chat/agent/${sid}/stream`, { method: "POST", json: { message }, headers });

describe("chat", () => {
  it("requires the session owner for messages", async () => {
    fakeAI();
    const alice = await registerAndLogin("alice@example.com");
    const bob = await registerAndLogin("bob@example.com");
    const sid = await newSession(alice);
    await ask(alice, sid);
    expect((await api(`/chat/agent/${sid}/messages`)).status).toBe(401);
    expect((await api(`/chat/agent/${sid}/messages`, { headers: bob })).status).toBe(404);
    const r = await api(`/chat/agent/${sid}/messages`, { headers: alice });
    expect(r.status).toBe(200);
    expect(await json(r)).toHaveLength(2);
  });

  it("streams the event sequence and saves the final answer", async () => {
    fakeAI();
    const headers = await registerAndLogin();
    const sid = await newSession(headers);
    const r = await stream(headers, sid, "cheap phone");
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toContain("text/event-stream");
    const events = parseSse(await r.text());
    expect(events.map((e) => e.status)).toEqual(["routing", "searching", "thinking", "completed"]);
    expect(events.slice(0, -1).every((e) => !("analysis" in e))).toBe(true);
    expect(events.at(-1).analysis).toBe("Best pick: Phone A");
    expect(events.at(-1).products).toHaveLength(2);

    const msgs = await json(await api(`/chat/agent/${sid}/messages`, { headers }));
    expect(msgs.map((m: any) => m.role)).toEqual(["user", "assistant"]);
    expect(msgs[1].content).toBe("Best pick: Phone A");
    expect(msgs[1].products[0].title).toBe("Phone A");
    expect(msgs[0].products).toBeNull();

    const sessions = await json(await api("/chat/sessions", { headers }));
    expect(sessions[0].title).toBe("cheap phone");
    expect(sessions[0].locked).toBe(false);
  });

  it("streams a refusal addressed to the user", async () => {
    const fake = fakeAI();
    fake.shopping = false;
    const headers = await registerAndLogin();
    const events = parseSse(await (await stream(headers, await newSession(headers), "weather?")).text());
    expect(events.map((e) => e.status)).toEqual(["routing", "out_of_scope"]);
    expect(events.at(-1).analysis).toContain("Ada");
  });

  it("ends the stream with an error event on failure", async () => {
    const fake = fakeAI();
    fake.failSearch = true;
    const headers = await registerAndLogin();
    const events = parseSse(await (await stream(headers, await newSession(headers), "phone")).text());
    expect(events.at(-1).status).toBe("error");
    expect(events.at(-1).analysis).toBeTruthy();
  });

  it("skips the analyst when nothing was found", async () => {
    const fake = fakeAI();
    fake.products = [];
    const headers = await registerAndLogin();
    const r = await ask(headers, await newSession(headers), "unobtainium");
    expect(r.status).toBe(200);
    const body = await json(r);
    expect(body.status).toBe("completed");
    expect(body.products).toEqual([]);
    expect(fake.calls.some((c) => c[0] === "analyst")).toBe(false);
  });

  it("passes history without duplicating the new question", async () => {
    const fake = fakeAI();
    const headers = await registerAndLogin();
    const sid = await newSession(headers);
    await ask(headers, sid, "first");
    fake.calls.length = 0;
    await ask(headers, sid, "cheaper one?");
    const [, question, history] = fake.calls[0];
    expect(question).toBe("cheaper one?");
    expect(history).toEqual(["Kullanıcı: first", "Asistan: Best pick: Phone A"]);
  });

  it("limits the message length", async () => {
    fakeAI();
    const headers = await registerAndLogin();
    expect((await ask(headers, await newSession(headers), "x".repeat(5000))).status).toBe(422);
  });

  it("renames and deletes sessions", async () => {
    fakeAI();
    const headers = await registerAndLogin();
    const other = await registerAndLogin("other@example.com");
    const sid = await newSession(headers);
    expect((await api(`/chat/sessions/${sid}`, { method: "PATCH", json: { title: "x" }, headers: other })).status).toBe(404);
    const r = await api(`/chat/sessions/${sid}`, { method: "PATCH", json: { title: "Laptops" }, headers });
    expect((await json(r)).title).toBe("Laptops");
    expect((await api(`/chat/sessions/${sid}`, { method: "DELETE", headers })).status).toBe(204);
    expect(await json(await api("/chat/sessions", { headers }))).toEqual([]);
  });
});

describe("plans and quota", () => {
  it("returns 402 quota_exceeded after five free messages", async () => {
    fakeAI();
    const headers = await registerAndLogin();
    const sid = await newSession(headers);
    for (let i = 0; i < 5; i++) expect((await ask(headers, sid)).status).toBe(200);
    let r = await ask(headers, sid);
    expect(r.status).toBe(402);
    let body = await json(r);
    expect(body.code).toBe("quota_exceeded");
    expect(typeof body.detail).toBe("string");
    r = await stream(headers, sid, "x");
    expect(r.status).toBe(402);
    expect((await json(r)).code).toBe("quota_exceeded");
    body = await json(await api("/user/me", { headers }));
    expect(body).toMatchObject({ plan: "free", usage_today: 5, daily_limit: 5, plan_expires_at: null });
  });

  it("doesn't spend quota on someone else's session", async () => {
    fakeAI();
    const alice = await registerAndLogin("alice@example.com");
    const bob = await registerAndLogin("bob@example.com");
    const sid = await newSession(alice);
    expect((await ask(bob, sid)).status).toBe(404);
    expect((await json(await api("/user/me", { headers: bob }))).usage_today).toBe(0);
  });

  it("sets products per search and the analyst model by tier", async () => {
    const fake = fakeAI();
    fake.products = Array.from({ length: 10 }, (_, i) => ({
      title: `P${i}`,
      price: i,
      source: "S",
      link: `https://${i}.example`,
      thumbnail: null,
    }));
    const headers = await registerAndLogin();
    const sid = await newSession(headers);
    expect((await json(await ask(headers, sid))).products).toHaveLength(3);
    expect((fake.calls.at(-1)![2] as any).model).toBe(DEFAULT_MODEL);

    await setPremium("user@example.com", new Date(Date.now() + 30 * 86_400_000).toISOString());
    expect((await json(await ask(headers, sid))).products).toHaveLength(8);
    expect((fake.calls.at(-1)![2] as any).model).toBe("gemini-2.5-flash");
    const me = await json(await api("/user/me", { headers }));
    expect(me.plan).toBe("premium");
    expect(me.daily_limit).toBe(100);
    expect(me.plan_expires_at).toBeTruthy();
  });

  it("treats expired premium as free", async () => {
    const headers = await registerAndLogin();
    await setPremium("user@example.com", new Date(Date.now() - 60_000).toISOString());
    const me = await json(await api("/user/me", { headers }));
    expect(me.plan).toBe("free");
    expect(me.daily_limit).toBe(5);
  });

  it("locks older sessions on the free plan", async () => {
    fakeAI();
    const headers = await registerAndLogin();
    const ids: number[] = [];
    for (let i = 0; i < 12; i++) ids.push(await newSession(headers));
    let sessions = await json(await api("/chat/sessions", { headers }));
    expect(sessions.map((s: any) => s.id)).toEqual([...ids].reverse());
    expect(sessions.map((s: any) => s.locked)).toEqual([...Array(10).fill(false), true, true]);

    const oldest = ids[0];
    let r = await api(`/chat/agent/${oldest}/messages`, { headers });
    expect(r.status).toBe(402);
    expect((await json(r)).code).toBe("history_locked");
    expect((await json(await ask(headers, oldest))).code).toBe("history_locked");
    expect((await json(await api("/user/me", { headers }))).usage_today).toBe(0);
    expect((await api(`/chat/sessions/${oldest}`, { method: "DELETE", headers })).status).toBe(204);

    await setPremium();
    sessions = await json(await api("/chat/sessions", { headers }));
    expect(sessions.some((s: any) => s.locked)).toBe(false);
    r = await api(`/chat/agent/${ids[1]}/messages`, { headers });
    expect(r.status).toBe(200);
  });
});
