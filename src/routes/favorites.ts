import { Hono } from "hono";
import type { AppEnv, Ctx } from "../context";
import { requirePremium, requireUser } from "../context";
import type { FavoriteRow } from "../db";
import { ApiError, notFound } from "../lib/errors";
import { nowIso } from "../lib/time";
import { parseJson, schemas } from "../lib/validation";

const favorites = new Hono<AppEnv>();
favorites.use("*", requireUser);

export function favoriteResponse(f: FavoriteRow) {
  return {
    id: f.id,
    user_id: f.user_id,
    title: f.title,
    price: f.price,
    currency: f.currency,
    source: f.source,
    link: f.link,
    thumbnail: f.thumbnail,
    target_price: f.target_price,
    last_checked_price: f.last_checked_price,
    last_checked_at: f.last_checked_at,
    added_at: f.created_at,
  };
}

const byLink = (c: Ctx, link: string) =>
  c.env.DB.prepare("SELECT * FROM favorites WHERE user_id = ? AND link = ?").bind(c.var.user.id, link).first<FavoriteRow>();

function favoriteId(c: Ctx): number {
  const id = Number(c.req.param("id"));
  if (!Number.isInteger(id) || id <= 0) throw new ApiError(422, "Geçersiz alan: favorite_id");
  return id;
}

/** Idempotent: adding an already-saved link returns the existing favorite (200). */
const add = async (c: Ctx) => {
  const body = await parseJson(c, schemas.favoriteCreate);
  const existing = await byLink(c, body.link);
  if (existing) return c.json(favoriteResponse(existing), 200);
  const row = await c.env.DB.prepare(
    `INSERT INTO favorites (user_id, title, price, currency, source, link, thumbnail, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (user_id, link) DO NOTHING
     RETURNING *`,
  )
    .bind(
      c.var.user.id,
      body.title,
      body.price,
      body.currency || c.var.user.currency,
      body.source ?? null,
      body.link,
      body.thumbnail ?? null,
      nowIso(),
    )
    .first<FavoriteRow>();
  // Raced with a concurrent add of the same link.
  if (!row) return c.json(favoriteResponse((await byLink(c, body.link))!), 200);
  return c.json(favoriteResponse(row), 201);
};

const list = async (c: Ctx) => {
  const { results } = await c.env.DB.prepare("SELECT * FROM favorites WHERE user_id = ? ORDER BY id DESC")
    .bind(c.var.user.id)
    .all<FavoriteRow>();
  return c.json(results.map(favoriteResponse));
};

// The apps call "/favorites/" (trailing slash); accept both.
favorites.post("/", add);
favorites.get("/", list);

favorites.delete("/by-link", async (c) => {
  const link = c.req.query("link") ?? "";
  if (!link || link.length > 2048) throw new ApiError(422, "Geçersiz alan: link");
  const res = await c.env.DB.prepare("DELETE FROM favorites WHERE user_id = ? AND link = ?").bind(c.var.user.id, link).run();
  if (!res.meta.changes) throw notFound("Favori ürün bulunamadı.");
  return c.body(null, 204);
});

/** Set or clear the price-alert target (premium). A new target re-arms the alert. */
favorites.patch("/:id", requirePremium, async (c) => {
  const body = await parseJson(c, schemas.favoriteUpdate);
  const row = await c.env.DB.prepare(
    "UPDATE favorites SET target_price = ?, last_notified_price = NULL WHERE id = ? AND user_id = ? RETURNING *",
  )
    .bind(body.target_price ?? null, favoriteId(c), c.var.user.id)
    .first<FavoriteRow>();
  if (!row) throw notFound("Favori ürün bulunamadı.");
  return c.json(favoriteResponse(row));
});

favorites.delete("/:id", async (c) => {
  const res = await c.env.DB.prepare("DELETE FROM favorites WHERE id = ? AND user_id = ?")
    .bind(favoriteId(c), c.var.user.id)
    .run();
  if (!res.meta.changes) throw notFound("Favori ürün bulunamadı.");
  return c.body(null, 204);
});

export default favorites;
