/**
 * Daily price check for premium users' price alerts (Cron Trigger).
 *
 * For every favorite with a `target_price` whose owner is premium, search the
 * product again (SerpAPI, exact title), find the same offer by link (or by
 * store + title), store the price, and push an FCM notification (Android + iOS)
 * when it is at or below the target. Also refreshes App Store subscriptions
 * that lapsed, when the App Store Server API key is configured.
 */
import type { Env } from "../env";
import type { DeviceTokenRow, FavoriteRow, UserRow } from "../db";
import { nowIso } from "../lib/time";
import { PLAN_PREMIUM, isPremium } from "../services/plan";
import * as push from "../services/push";
import * as apple from "../services/appleBilling";
import { SearchError, searchProducts, type Product } from "../services/search";

const SEARCH_LIMIT = 20;
/** Upper bound per run, to stay inside one invocation's subrequest budget. */
const MAX_FAVORITES_PER_RUN = 200;

const ALERT_TEXT: Record<string, [string, string]> = {
  tr: ["Fiyat düştü!", "{title} şimdi {price} ({source}). Hedefin: {target}."],
  en: ["Price drop!", "{title} is now {price} ({source}). Your target: {target}."],
};

const norm = (s: string | null | undefined) => (s || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");

/** The same offer: identical link first, else same store with the same title. */
export function matchOffer(favorite: Pick<FavoriteRow, "link" | "source" | "title">, results: Product[]): Product | null {
  return (
    results.find((r) => r.link === favorite.link) ??
    results.find((r) => norm(r.source) === norm(favorite.source) && norm(r.title) === norm(favorite.title)) ??
    null
  );
}

const formatPrice = (amount: number, currency: string | null) =>
  `${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency || ""}`.trim();

export function shouldNotify(favorite: Pick<FavoriteRow, "target_price" | "last_notified_price">, price: number): boolean {
  if (favorite.target_price === null || price > favorite.target_price) return false;
  // Notify once per drop: again only if it falls below the last alerted price.
  return favorite.last_notified_price === null || price < favorite.last_notified_price;
}

async function notify(env: Env, user: UserRow, favorite: FavoriteRow, price: number): Promise<boolean> {
  const { results: tokens } = await env.DB.prepare("SELECT * FROM device_tokens WHERE user_id = ?")
    .bind(user.id)
    .all<DeviceTokenRow>();
  if (!tokens.length) return false;
  const [title, template] = ALERT_TEXT[(user.language || "tr").toLowerCase()] ?? ALERT_TEXT.en;
  const body = template
    .replace("{title}", (favorite.title || "").slice(0, 60))
    .replace("{price}", formatPrice(price, favorite.currency))
    .replace("{source}", favorite.source || "-")
    .replace("{target}", formatPrice(favorite.target_price!, favorite.currency));
  const data = { type: "price_alert", favorite_id: String(favorite.id), link: favorite.link, price: String(price) };
  let sent = false;
  for (const device of tokens) {
    try {
      await push.send(env, device.token, title, body, data);
      sent = true;
    } catch (e) {
      if (e instanceof push.InvalidToken) {
        await env.DB.prepare("DELETE FROM device_tokens WHERE id = ?").bind(device.id).run();
      } else {
        console.error(`FCM send failed (user=${user.id})`, (e as Error).message);
      }
    }
  }
  return sent;
}

type Row = FavoriteRow & { u_language: string; u_currency: string; u_plan: string; u_plan_expires_at: string | null };

export async function runPriceCheck(env: Env) {
  const stats = { checked: 0, matched: 0, notified: 0, errors: 0 };
  const pushOn = push.isConfigured(env);
  if (!pushOn) console.warn("FCM is not configured; prices are checked but no alerts are sent");

  const { results } = await env.DB.prepare(
    `SELECT f.*, u.language AS u_language, u.currency AS u_currency, u.plan AS u_plan, u.plan_expires_at AS u_plan_expires_at
     FROM favorites f JOIN users u ON u.id = f.user_id
     WHERE f.target_price IS NOT NULL AND u.plan = ?
     ORDER BY f.last_checked_at IS NOT NULL, f.last_checked_at
     LIMIT ?`,
  )
    .bind(PLAN_PREMIUM, MAX_FAVORITES_PER_RUN)
    .all<Row>();

  for (const row of results) {
    const owner = { plan: row.u_plan, plan_expires_at: row.u_plan_expires_at } as UserRow;
    if (!isPremium(owner)) continue; // expired
    stats.checked++;
    let found: Product[];
    try {
      found = await searchProducts(env, row.title, row.u_language, row.currency || row.u_currency, SEARCH_LIMIT);
    } catch (e) {
      if (!(e instanceof SearchError)) throw e;
      stats.errors++;
      console.warn(`Price search failed (favorite=${row.id})`);
      continue;
    }
    const offer = matchOffer(row, found);
    if (!offer || offer.price === null) {
      await env.DB.prepare("UPDATE favorites SET last_checked_at = ? WHERE id = ?").bind(nowIso(), row.id).run();
      continue;
    }
    stats.matched++;
    const price = Number(offer.price);
    await env.DB.prepare("UPDATE favorites SET last_checked_at = ?, last_checked_price = ? WHERE id = ?")
      .bind(nowIso(), price, row.id)
      .run();

    if (pushOn && shouldNotify(row, price)) {
      const user = { id: row.user_id, language: row.u_language } as UserRow;
      if (await notify(env, user, row, price)) {
        await env.DB.prepare("UPDATE favorites SET last_notified_price = ? WHERE id = ?").bind(price, row.id).run();
        stats.notified++;
      }
    }
  }
  return stats;
}

/** Re-checks App Store subscriptions whose expiry passed in the last 3 days (missed notifications). */
export async function refreshAppleSubscriptions(env: Env) {
  if (!apple.serverApiConfigured(env)) return { refreshed: 0 };
  const since = new Date(Date.now() - 3 * 86_400_000).toISOString();
  const { results } = await env.DB.prepare(
    `SELECT * FROM users WHERE plan_source = 'apple' AND apple_original_transaction_id IS NOT NULL
     AND plan_expires_at IS NOT NULL AND plan_expires_at BETWEEN ? AND ? LIMIT 100`,
  )
    .bind(since, nowIso())
    .all<UserRow>();
  let refreshed = 0;
  for (const user of results) {
    try {
      const status = await apple.fetchLatestStatus(env, user.apple_original_transaction_id!);
      if (status) {
        await apple.applyAppleTransaction(env, user, status.tx, status.renewal);
        refreshed++;
      }
    } catch (e) {
      console.warn(`App Store status refresh failed (user=${user.id})`, (e as Error).message);
    }
  }
  return { refreshed };
}
