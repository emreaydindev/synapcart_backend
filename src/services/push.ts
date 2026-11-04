/**
 * Firebase Cloud Messaging (HTTP v1) for price alerts, on Android and iOS.
 * iOS tokens are FCM registration tokens too (the app uses the Firebase SDK and
 * an APNs key uploaded to Firebase), so one code path serves both platforms.
 */
import type { Env } from "../env";
import { SCOPE_FCM, accessToken, loadServiceAccount, type ServiceAccount } from "./google";

const FCM_URL = (project: string) => `https://fcm.googleapis.com/v1/projects/${project}/messages:send`;

// Must match the channel the Android app creates.
export const ANDROID_CHANNEL_ID = "price_alerts";

export class PushNotConfigured extends Error {}
/** The device token is no longer registered; delete it. */
export class InvalidToken extends Error {}
export class PushError extends Error {}

function accountAndProject(env: Env): [ServiceAccount, string] {
  const account = loadServiceAccount(env.FIREBASE_SERVICE_ACCOUNT_JSON);
  if (!account) throw new PushNotConfigured();
  const project = env.FIREBASE_PROJECT_ID || account.project_id;
  if (!project) throw new PushNotConfigured();
  return [account, project];
}

export function isConfigured(env: Env): boolean {
  try {
    accountAndProject(env);
    return true;
  } catch {
    return false;
  }
}

export async function send(env: Env, token: string, title: string, body: string, data: Record<string, string> = {}) {
  const [account, project] = accountAndProject(env);
  const access = await accessToken(account, SCOPE_FCM);
  const message = {
    message: {
      token,
      notification: { title, body },
      data,
      android: { priority: "high", notification: { channel_id: ANDROID_CHANNEL_ID } },
      apns: {
        headers: { "apns-priority": "10" },
        payload: { aps: { sound: "default", "thread-id": "price_alerts" } },
      },
    },
  };
  const res = await fetch(FCM_URL(project), {
    method: "POST",
    headers: { Authorization: `Bearer ${access}`, "Content-Type": "application/json" },
    body: JSON.stringify(message),
    signal: AbortSignal.timeout(15_000),
  });
  const text = await res.text();
  if (res.status === 404 || text.includes("UNREGISTERED")) throw new InvalidToken();
  if (!res.ok) throw new PushError(`FCM returned ${res.status}`);
}
