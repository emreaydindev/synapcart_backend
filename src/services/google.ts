/**
 * OAuth2 access tokens for Google service accounts (Play Developer API, FCM),
 * using the JWT-bearer flow with `jose` (no google-auth dependency).
 */
import { SignJWT, importPKCS8 } from "jose";

export const TOKEN_URI = "https://oauth2.googleapis.com/token";
export const SCOPE_ANDROID_PUBLISHER = "https://www.googleapis.com/auth/androidpublisher";
export const SCOPE_FCM = "https://www.googleapis.com/auth/firebase.messaging";

export interface ServiceAccount {
  client_email: string;
  private_key: string;
  private_key_id?: string;
  project_id?: string;
  token_uri?: string;
}

export class GoogleAuthError extends Error {}

/** `value` is the key file's JSON content; empty = not configured. */
export function loadServiceAccount(value: string | undefined): ServiceAccount | null {
  const v = (value || "").trim();
  if (!v) return null;
  try {
    return JSON.parse(v) as ServiceAccount;
  } catch {
    throw new GoogleAuthError("Invalid service account JSON");
  }
}

// Per-isolate cache: (client_email, scope) -> [expiresAtMs, token]
const cache = new Map<string, [number, string]>();

export function clearTokenCache() {
  cache.clear();
}

export async function accessToken(account: ServiceAccount, scope: string): Promise<string> {
  const key = `${account.client_email}|${scope}`;
  const hit = cache.get(key);
  if (hit && hit[0] - 60_000 > Date.now()) return hit[1];

  const tokenUri = account.token_uri || TOKEN_URI;
  let assertion: string;
  try {
    const pk = await importPKCS8(account.private_key, "RS256");
    const now = Math.floor(Date.now() / 1000);
    assertion = await new SignJWT({ scope })
      .setProtectedHeader({ alg: "RS256", typ: "JWT", kid: account.private_key_id || "" })
      .setIssuer(account.client_email)
      .setAudience(tokenUri)
      .setIssuedAt(now)
      .setExpirationTime(now + 3600)
      .sign(pk);
  } catch {
    throw new GoogleAuthError("Could not sign service account assertion");
  }

  let data: { access_token?: string; expires_in?: number };
  try {
    const res = await fetch(tokenUri, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion }),
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (e) {
    throw new GoogleAuthError(`Token exchange failed: ${(e as Error).message}`);
  }
  if (!data.access_token) throw new GoogleAuthError("Token exchange returned no access_token");
  cache.set(key, [Date.now() + (data.expires_in ?? 3600) * 1000, data.access_token]);
  return data.access_token;
}
