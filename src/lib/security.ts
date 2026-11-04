import { SignJWT, jwtVerify } from "jose";
import type { Env } from "../env";
import { settings } from "../config";

const enc = new TextEncoder();
const keyFor = (env: Env) => enc.encode(env.SECRET_KEY);

/** HS256 JWT: `sub` is the user's email, `tv` the user's token_version. */
export async function createAccessToken(env: Env, email: string, tokenVersion: number, expiresInMinutes?: number) {
  const minutes = expiresInMinutes ?? settings(env).accessTokenMinutes;
  return new SignJWT({ tv: tokenVersion })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setSubject(email)
    .setExpirationTime(Math.floor(Date.now() / 1000) + minutes * 60)
    .sign(keyFor(env));
}

export async function decodeAccessToken(env: Env, token: string): Promise<{ sub: string; tv: number } | null> {
  try {
    const { payload } = await jwtVerify(token, keyFor(env), { algorithms: ["HS256"] });
    if (typeof payload.sub !== "string" || !payload.sub) return null;
    return { sub: payload.sub, tv: Number(payload.tv ?? 0) };
  } catch {
    return null;
  }
}

export const buildResetUrl = (env: Env, token: string) =>
  `${settings(env).frontendUrl}/reset-password?token=${encodeURIComponent(token)}`;

export const buildDeleteUrl = (env: Env, token: string) =>
  `${settings(env).frontendUrl}/delete-account?token=${encodeURIComponent(token)}`;
