import { Hono } from "hono";
import type { AppEnv, Ctx } from "../context";
import { rateLimit } from "../context";
import { getUserByEmail, updateUser, deleteUser, type UserRow } from "../db";
import { settings } from "../config";
import { ApiError, badRequest } from "../lib/errors";
import { hashPassword, needsRehash, verifyPassword } from "../lib/password";
import { createAccessToken } from "../lib/security";
import { randomToken, sha256Hex } from "../lib/crypto";
import { HOUR, MINUTE, addMs, isPast, nowIso } from "../lib/time";
import { parseJson, schemas } from "../lib/validation";
import { sendDeleteEmail, sendResetEmail } from "../services/email";
import { profileResponse } from "../services/profile";

export const FORGOT_PASSWORD_MESSAGE = "Bu email adresiyle ilişkili bir hesap varsa, şifre sıfırlama linki göndereceğiz.";
export const DELETE_REQUEST_MESSAGE = "Bu email adresiyle ilişkili bir hesap varsa, hesap silme onay linki göndereceğiz.";
// Minimum gap between two reset (or delete) emails for the same account.
const EMAIL_COOLDOWN_MS = 2 * MINUTE;

export async function issueToken(c: Ctx, user: UserRow) {
  return {
    access_token: await createAccessToken(c.env, user.email, user.token_version ?? 0),
    token_type: "bearer",
    user_name: user.full_name,
  };
}

async function authenticate(c: Ctx, email: string, password: string): Promise<UserRow> {
  const user = await getUserByEmail(c.env.DB, email);
  if (!user || !(await verifyPassword(password, user.hashed_password))) {
    throw new ApiError(401, "Hatalı email veya şifre.");
  }
  const iterations = settings(c.env).passwordIterations;
  if (needsRehash(user.hashed_password, iterations)) {
    return updateUser(c.env.DB, user.id, { hashed_password: await hashPassword(password, iterations) });
  }
  return user;
}

/** True when a link was sent less than the cooldown ago (expiry - lifetime = sent time). */
const inCooldown = (expires: string | null, lifetimeMs: number) =>
  !!expires && new Date(expires).getTime() - lifetimeMs > Date.now() - EMAIL_COOLDOWN_MS;

const auth = new Hono<AppEnv>();

auth.post("/register", rateLimit("AUTH_LIMITER", "register"), async (c) => {
  const body = await parseJson(c, schemas.register);
  if (await getUserByEmail(c.env.DB, body.email)) throw badRequest("Bu email zaten kayıtlı.");
  const id = crypto.randomUUID();
  await c.env.DB.prepare("INSERT INTO users (id, email, hashed_password, full_name, created_at) VALUES (?, ?, ?, ?, ?)")
    .bind(id, body.email, await hashPassword(body.password, settings(c.env).passwordIterations), body.name, nowIso())
    .run();
  const user = (await getUserByEmail(c.env.DB, body.email))!;
  return c.json(await profileResponse(c.env, user), 201);
});

auth.post("/login", rateLimit("AUTH_LIMITER", "login"), async (c) => {
  const body = await parseJson(c, schemas.login);
  return c.json(await issueToken(c, await authenticate(c, body.email, body.password)));
});

/** OAuth2 password-form login (username = email), for API tools. Disabled in production. */
auth.post("/token", rateLimit("AUTH_LIMITER", "login"), async (c) => {
  if (settings(c.env).isProd) throw new ApiError(404, "Not Found");
  const form = await c.req.parseBody();
  const user = await authenticate(c, String(form.username ?? ""), String(form.password ?? ""));
  return c.json(await issueToken(c, user));
});

auth.post("/forgot-password", rateLimit("EMAIL_LIMITER", "forgot"), async (c) => {
  const body = await parseJson(c, schemas.emailOnly);
  const user = await getUserByEmail(c.env.DB, body.email);
  const lifetime = settings(c.env).resetTokenHours * HOUR;
  if (!user || inCooldown(user.reset_token_expires, lifetime)) return c.json({ message: FORGOT_PASSWORD_MESSAGE });

  const raw = randomToken();
  await updateUser(c.env.DB, user.id, { reset_token: await sha256Hex(raw), reset_token_expires: addMs(lifetime) });
  try {
    await sendResetEmail(c.env, user.email, raw);
  } catch (e) {
    console.error("Failed to send password reset email", (e as Error).message);
    await updateUser(c.env.DB, user.id, { reset_token: null, reset_token_expires: null });
    // Same response as for unknown emails so accounts can't be enumerated.
  }
  return c.json({ message: FORGOT_PASSWORD_MESSAGE });
});

auth.post("/reset-password", rateLimit("AUTH_LIMITER", "reset"), async (c) => {
  const body = await parseJson(c, schemas.resetPassword);
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE reset_token = ?")
    .bind(await sha256Hex(body.token))
    .first<UserRow>();
  if (!user) throw badRequest("Geçersiz şifre sıfırlama linki.");
  if (!user.reset_token_expires || isPast(user.reset_token_expires)) {
    await updateUser(c.env.DB, user.id, { reset_token: null, reset_token_expires: null });
    throw badRequest("Şifre sıfırlama linkinin süresi dolmuş.");
  }
  await updateUser(c.env.DB, user.id, {
    hashed_password: await hashPassword(body.new_password, settings(c.env).passwordIterations),
    reset_token: null,
    reset_token_expires: null,
    token_version: (user.token_version ?? 0) + 1,
  });
  return c.json({ message: "Şifreniz başarıyla sıfırlandı." });
});

/** Web account deletion (the store listings' deletion URL): email a single-use confirm link. */
auth.post("/delete-request", rateLimit("EMAIL_LIMITER", "delete"), async (c) => {
  const body = await parseJson(c, schemas.emailOnly);
  const user = await getUserByEmail(c.env.DB, body.email);
  const lifetime = settings(c.env).deleteTokenHours * HOUR;
  if (!user || inCooldown(user.delete_token_expires, lifetime)) return c.json({ message: DELETE_REQUEST_MESSAGE });

  const raw = randomToken();
  await updateUser(c.env.DB, user.id, { delete_token: await sha256Hex(raw), delete_token_expires: addMs(lifetime) });
  try {
    await sendDeleteEmail(c.env, user.email, raw);
  } catch (e) {
    console.error("Failed to send account deletion email", (e as Error).message);
    await updateUser(c.env.DB, user.id, { delete_token: null, delete_token_expires: null });
  }
  return c.json({ message: DELETE_REQUEST_MESSAGE });
});

auth.post("/delete-confirm", rateLimit("AUTH_LIMITER", "delete-confirm"), async (c) => {
  const body = await parseJson(c, schemas.tokenOnly);
  const user = await c.env.DB.prepare("SELECT * FROM users WHERE delete_token = ?")
    .bind(await sha256Hex(body.token))
    .first<UserRow>();
  if (!user) throw badRequest("Geçersiz hesap silme linki.");
  if (!user.delete_token_expires || isPast(user.delete_token_expires)) {
    await updateUser(c.env.DB, user.id, { delete_token: null, delete_token_expires: null });
    throw badRequest("Hesap silme linkinin süresi dolmuş.");
  }
  await deleteUser(c.env.DB, user.id);
  console.log("Account deleted via web confirmation");
  return c.json({ message: "Hesabınız ve tüm verileriniz silindi." });
});

export default auth;
