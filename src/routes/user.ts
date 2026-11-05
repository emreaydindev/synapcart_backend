import { Hono } from "hono";
import type { AppEnv } from "../context";
import { requireUser } from "../context";
import { deleteUser, updateUser, type UserRow } from "../db";
import { settings } from "../config";
import { ApiError } from "../lib/errors";
import { hashPassword, verifyPassword } from "../lib/password";
import { nowIso } from "../lib/time";
import { parseJson, schemas } from "../lib/validation";
import { profileResponse } from "../services/profile";
import { issueToken } from "./auth";

const user = new Hono<AppEnv>();
user.use("*", requireUser);

user.get("/me", async (c) => c.json(await profileResponse(c.env, c.var.user)));

user.patch("/me", async (c) => {
  const body = await parseJson(c, schemas.profileUpdate);
  const fields: Partial<UserRow> = {};
  if (body.full_name != null) fields.full_name = body.full_name;
  if (body.language) fields.language = body.language;
  if (body.currency) fields.currency = body.currency;
  const fresh = await updateUser(c.env.DB, c.var.user.id, fields);
  return c.json(await profileResponse(c.env, fresh));
});

/** Register (or move to this user) an FCM token, Android or iOS. Idempotent. */
user.post("/me/device-token", async (c) => {
  const body = await parseJson(c, schemas.deviceToken);
  const now = nowIso();
  await c.env.DB.prepare(
    `INSERT INTO device_tokens (user_id, token, platform, created_at, updated_at) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (token) DO UPDATE SET user_id = excluded.user_id, platform = excluded.platform, updated_at = excluded.updated_at`,
  )
    .bind(c.var.user.id, body.token, body.platform ?? "android", now, now)
    .run();
  return c.body(null, 204);
});

/** Called on logout so the device stops receiving this user's alerts. */
user.delete("/me/device-token", async (c) => {
  const body = await parseJson(c, schemas.deviceToken);
  await c.env.DB.prepare("DELETE FROM device_tokens WHERE token = ? AND user_id = ?").bind(body.token, c.var.user.id).run();
  return c.body(null, 204);
});

user.post("/me/password", async (c) => {
  const body = await parseJson(c, schemas.changePassword);
  const me = c.var.user;
  if (!(await verifyPassword(body.current_password, me.hashed_password))) {
    throw new ApiError(403, "Mevcut şifre hatalı.");
  }
  const fresh = await updateUser(c.env.DB, me.id, {
    hashed_password: await hashPassword(body.new_password, settings(c.env).passwordIterations),
    token_version: (me.token_version ?? 0) + 1,
  });
  // Other devices are logged out; this one gets a fresh token.
  return c.json(await issueToken(c, fresh));
});

/**
 * In-app account deletion (required by both stores). The optional {password}
 * body is verified when present. An active store subscription is not cancelled
 * by this; the apps tell the user to cancel it in the store.
 */
user.delete("/me", async (c) => {
  const body = await parseJson(c, schemas.deleteAccount, true);
  const me = c.var.user;
  if (body.password != null && !(await verifyPassword(body.password, me.hashed_password))) {
    throw new ApiError(403, "Şifre hatalı.");
  }
  await deleteUser(c.env.DB, me.id);
  return c.body(null, 204);
});

export default user;
