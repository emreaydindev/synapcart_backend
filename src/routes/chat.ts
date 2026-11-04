import { Hono } from "hono";
import type { AppEnv, Ctx } from "../context";
import { rateLimit, requirePremium, requireUser } from "../context";
import type { MessageRow, SessionRow, UserRow } from "../db";
import { ApiError, historyLocked, notFound, quotaExceeded } from "../lib/errors";
import { nowIso } from "../lib/time";
import { parseJson, schemas } from "../lib/validation";
import { ERROR_MESSAGES, defaultDeps, localized, runAgent, streamAgent, type AgentEvent, type AgentInput } from "../services/agent";
import {
  DEFAULT_SESSION_TITLE,
  getOwnedSession,
  isSessionLocked,
  loadHistory,
  messageResponse,
  saveMessage,
} from "../services/chat";
import { GeminiError, compareProducts } from "../services/gemini";
import { getLimits, recordMessage, usageToday, type PlanLimits } from "../services/plan";

const chat = new Hono<AppEnv>();
chat.use("*", requireUser);

const sessionResponse = (s: SessionRow, locked = false) => ({ ...s, locked });

function sessionId(c: Ctx): number {
  const id = Number(c.req.param("id"));
  if (!Number.isInteger(id) || id <= 0) throw new ApiError(422, "Geçersiz alan: session_id");
  return id;
}

async function requireSession(c: Ctx, id: number): Promise<SessionRow> {
  const session = await getOwnedSession(c.env.DB, id, c.var.user.id);
  if (!session) throw notFound("Oturum bulunamadı.");
  return session;
}

async function requireUnlocked(c: Ctx, session: SessionRow, limits: PlanLimits) {
  if (await isSessionLocked(c.env.DB, session, limits.maxSessions)) throw historyLocked();
}

/**
 * Shared by both agent routes: quota check, ownership, history lock, then count
 * and save the question. A 404 or locked session costs no quota.
 */
async function startAgentTurn(c: Ctx, message: string): Promise<{ id: number; input: AgentInput }> {
  const user: UserRow = c.var.user;
  const limits = getLimits(c.env, user);
  if ((await usageToday(c.env.DB, user.id)) >= limits.dailyMessages) throw quotaExceeded(limits.dailyMessages);
  const id = sessionId(c);
  const session = await requireSession(c, id);
  await requireUnlocked(c, session, limits);
  // History is loaded *before* the new message is saved so it isn't duplicated.
  const input: AgentInput = {
    question: message,
    history: await loadHistory(c.env.DB, id),
    userName: user.full_name || "",
    language: user.language || "tr",
    currency: user.currency || "TRY",
    maxProducts: limits.maxProducts,
    analystModel: limits.analystModel,
  };
  await recordMessage(c.env.DB, user.id);
  await saveMessage(c.env.DB, id, "user", message);
  return { id, input };
}

// --- Sessions ---

/** Newest first. On the free plan, sessions past the most recent 10 are `locked`. */
chat.get("/sessions", async (c) => {
  const { results } = await c.env.DB.prepare("SELECT * FROM chat_sessions WHERE user_id = ? ORDER BY id DESC")
    .bind(c.var.user.id)
    .all<SessionRow>();
  const max = getLimits(c.env, c.var.user).maxSessions;
  return c.json(results.map((s, i) => sessionResponse(s, max !== null && i >= max)));
});

chat.post("/sessions", async (c) => {
  const row = await c.env.DB.prepare("INSERT INTO chat_sessions (user_id, title, created_at) VALUES (?, ?, ?) RETURNING *")
    .bind(c.var.user.id, DEFAULT_SESSION_TITLE, nowIso())
    .first<SessionRow>();
  return c.json(sessionResponse(row!));
});

chat.patch("/sessions/:id", async (c) => {
  const body = await parseJson(c, schemas.sessionUpdate);
  const session = await requireSession(c, sessionId(c));
  const row = await c.env.DB.prepare("UPDATE chat_sessions SET title = ? WHERE id = ? RETURNING *")
    .bind(body.title.trim(), session.id)
    .first<SessionRow>();
  return c.json(sessionResponse(row!));
});

chat.delete("/sessions/:id", async (c) => {
  const session = await requireSession(c, sessionId(c));
  await c.env.DB.prepare("DELETE FROM chat_sessions WHERE id = ?").bind(session.id).run();
  return c.body(null, 204);
});

chat.get("/agent/:id/messages", async (c) => {
  const session = await requireSession(c, sessionId(c));
  await requireUnlocked(c, session, getLimits(c.env, c.var.user));
  const { results } = await c.env.DB.prepare("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC")
    .bind(session.id)
    .all<MessageRow>();
  return c.json(results.map(messageResponse));
});

// --- Agent ---

chat.post("/agent/:id", rateLimit("AGENT_LIMITER", "agent"), async (c) => {
  const body = await parseJson(c, schemas.chat);
  const { id, input } = await startAgentTurn(c, body.message);
  let result: AgentEvent;
  try {
    result = await runAgent(c.env, input, defaultDeps);
  } catch (e) {
    console.error(`Agent run failed (session=${id})`, (e as Error).message);
    throw new ApiError(502, localized(ERROR_MESSAGES, c.var.user.language));
  }
  const analysis = result.analysis ?? "";
  const products = result.status === "completed" ? (result.products ?? []) : [];
  await saveMessage(c.env.DB, id, "assistant", analysis, products);
  return c.json({ status: result.status, analysis, products });
});

const sse = (event: object) => `data: ${JSON.stringify(event)}\n\n`;

chat.post("/agent/:id/stream", rateLimit("AGENT_LIMITER", "agent"), async (c) => {
  const body = await parseJson(c, schemas.chat);
  const { id, input } = await startAgentTurn(c, body.message);
  const language = c.var.user.language;
  const db = c.env.DB;
  const env = c.env;
  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let final: AgentEvent | null = null;
      try {
        for await (const event of streamAgent(env, input, defaultDeps)) {
          if (event.status === "completed" || event.status === "out_of_scope") final = event;
          controller.enqueue(encoder.encode(sse(event)));
        }
      } catch (e) {
        console.error(`Agent stream failed (session=${id})`, (e as Error).message);
        controller.enqueue(encoder.encode(sse({ status: "error", analysis: localized(ERROR_MESSAGES, language) })));
        controller.close();
        return;
      }
      if (final?.analysis) await saveMessage(db, id, "assistant", final.analysis, final.products);
      controller.close();
    },
  });
  return new Response(stream, {
    headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
  });
});

// --- Comparison (premium) ---

const COMPARE_ERROR: Record<string, string> = {
  tr: "Karşılaştırma şu an yapılamadı, lütfen birazdan tekrar dene.",
  en: "The comparison couldn't be made right now, please try again shortly.",
};

/** Structured pros/cons per product plus a verdict, in the user's language. */
chat.post("/compare", requirePremium, rateLimit("AGENT_LIMITER", "agent"), async (c) => {
  const body = await parseJson(c, schemas.compare);
  const user = c.var.user;
  const products = body.products;
  let data;
  try {
    data = await compareProducts(c.env, products, {
      currency: user.currency || "TRY",
      language: user.language || "tr",
      model: getLimits(c.env, user).analystModel,
    });
  } catch (e) {
    if (!(e instanceof GeminiError)) throw e;
    console.error("Comparison failed", e.message);
    throw new ApiError(502, localized(COMPARE_ERROR, user.language));
  }
  const raw = Array.isArray(data.items) ? data.items : [];
  // One item per requested product, in order, even if the model returned fewer.
  const items = products.map((p, i) => {
    const r = raw[i] && typeof raw[i] === "object" ? raw[i] : {};
    const strs = (v: unknown) => (Array.isArray(v) ? v.filter(Boolean).map(String) : []);
    return { title: p.title, link: p.link ?? null, pros: strs(r.pros).slice(0, 4), cons: strs(r.cons).slice(0, 3) };
  });
  const best = Number.isInteger(data.best_index) && data.best_index! >= 0 && data.best_index! < products.length ? data.best_index : null;
  return c.json({ items, verdict: String(data.verdict ?? ""), best_index: best });
});

export default chat;
