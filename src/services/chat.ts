import type { MessageRow, SessionRow } from "../db";
import { nowIso } from "../lib/time";
import type { Product } from "./search";

export const DEFAULT_SESSION_TITLE = "Yeni Sohbet";
const HISTORY_MESSAGES = 6;
const HISTORY_CHARS_PER_MESSAGE = 500;

export const getOwnedSession = (db: D1Database, sessionId: number, userId: string) =>
  db.prepare("SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?").bind(sessionId, userId).first<SessionRow>();

/** A session is locked when the user has `maxSessions` newer ones. */
export async function isSessionLocked(db: D1Database, session: SessionRow, maxSessions: number | null): Promise<boolean> {
  if (maxSessions === null) return false;
  const row = await db
    .prepare("SELECT COUNT(*) AS n FROM chat_sessions WHERE user_id = ? AND id > ?")
    .bind(session.user_id, session.id)
    .first<{ n: number }>();
  return (row?.n ?? 0) >= maxSessions;
}

/** Most recent messages, oldest first, as 'Kullanıcı: ...' / 'Asistan: ...' lines. */
export async function loadHistory(db: D1Database, sessionId: number, limit = HISTORY_MESSAGES): Promise<string[]> {
  const { results } = await db
    .prepare("SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?")
    .bind(sessionId, limit)
    .all<Pick<MessageRow, "role" | "content">>();
  return results
    .reverse()
    .map((m) => `${m.role === "user" ? "Kullanıcı" : "Asistan"}: ${(m.content || "").slice(0, HISTORY_CHARS_PER_MESSAGE)}`);
}

export async function saveMessage(
  db: D1Database,
  sessionId: number,
  role: "user" | "assistant",
  content: string,
  products?: Product[] | null,
): Promise<void> {
  const stmts = [
    db
      .prepare("INSERT INTO chat_messages (session_id, role, content, products, created_at) VALUES (?, ?, ?, ?, ?)")
      .bind(sessionId, role, content, products && products.length ? JSON.stringify(products) : null, nowIso()),
  ];
  if (role === "user") {
    const title = content.length > 30 ? `${content.slice(0, 30)}...` : content;
    stmts.push(
      db
        .prepare("UPDATE chat_sessions SET title = ? WHERE id = ? AND (title IS NULL OR title = ?)")
        .bind(title, sessionId, DEFAULT_SESSION_TITLE),
    );
  }
  try {
    await db.batch(stmts);
  } catch (e) {
    console.error("Failed to save chat message", (e as Error).message);
  }
}

export function messageResponse(m: MessageRow) {
  let products: unknown = null;
  if (m.products) {
    try {
      products = JSON.parse(m.products);
    } catch {
      products = null;
    }
  }
  return { id: m.id, session_id: m.session_id, role: m.role, content: m.content || "", products, created_at: m.created_at };
}
