import { b64Decode, b64urlEncode, safeEqual } from "./crypto";

// PBKDF2-SHA256 through WebCrypto (native, cheap on Workers CPU time).
// 100k iterations is the maximum the Workers runtime accepts.
const ITERATIONS = 100_000;
const enc = new TextEncoder();

async function derive(password: string, salt: Uint8Array<ArrayBuffer>, iterations: number): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, 256);
  return new Uint8Array(bits);
}

/** Stored as `pbkdf2_sha256$<iterations>$<salt b64url>$<hash b64url>`. */
export async function hashPassword(password: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const hash = await derive(password, salt, ITERATIONS);
  return `pbkdf2_sha256$${ITERATIONS}$${b64urlEncode(salt)}$${b64urlEncode(hash)}`;
}

export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const [scheme, iter, salt, hash] = stored.split("$");
  if (scheme !== "pbkdf2_sha256" || !iter || !salt || !hash) return false;
  try {
    const actual = await derive(password, b64Decode(salt), Number(iter));
    return safeEqual(b64urlEncode(actual), hash);
  } catch {
    return false;
  }
}
