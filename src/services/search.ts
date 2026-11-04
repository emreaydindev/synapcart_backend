/** Product search via SerpAPI's google_shopping engine, cached for 30 minutes in the Workers Cache API. */
import type { Env } from "../env";
import { settings } from "../config";

export interface Product {
  title: string;
  price: number | null;
  source: string | null;
  link: string;
  thumbnail: string | null;
}

export class SearchError extends Error {}

const SERP_URL = "https://serpapi.com/search";
const CACHE_TTL_SECONDS = 30 * 60;

const LANG_MAP: Record<string, { hl: string; gl: string; location: string }> = {
  tr: { hl: "tr", gl: "tr", location: "Turkey" },
  en: { hl: "en", gl: "us", location: "United States" },
  ar: { hl: "ar", gl: "sa", location: "Saudi Arabia" },
  ru: { hl: "ru", gl: "ru", location: "Russian Federation" },
  fr: { hl: "fr", gl: "fr", location: "France" },
  de: { hl: "de", gl: "de", location: "Germany" },
  es: { hl: "es", gl: "es", location: "Spain" },
  it: { hl: "it", gl: "it", location: "Italy" },
  zh: { hl: "zh-cn", gl: "cn", location: "China" },
  ja: { hl: "ja", gl: "jp", location: "Japan" },
};

export function getSerpParams(query: string, language: string | null = "tr", currency: string | null = "TRY") {
  const lang = (language || "tr").toLowerCase();
  const params: Record<string, string> = { engine: "google_shopping", q: query, ...(LANG_MAP[lang] ?? LANG_MAP.tr) };
  if (currency === "TRY") Object.assign(params, { gl: "tr", location: "Turkey" });
  else if (currency === "EUR" && !["fr", "de", "es", "it"].includes(lang)) Object.assign(params, { gl: "de", location: "Germany" });
  else if (currency === "USD" && lang !== "en") Object.assign(params, { gl: "us", location: "United States" });
  else if (currency === "GBP") Object.assign(params, { gl: "uk", location: "United Kingdom" });
  return params;
}

function clean(item: any): Product | null {
  const link = item?.product_link || item?.link;
  const title = item?.title;
  if (!link || !title) return null;
  return {
    title,
    price: typeof item.extracted_price === "number" ? item.extracted_price : null,
    source: item.source ?? null,
    link,
    thumbnail: item.thumbnail ?? null,
  };
}

function cacheKey(params: Record<string, string>): Request {
  const sorted = Object.keys(params)
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join("&");
  // Synthetic URL: only used as a cache key, never fetched.
  return new Request(`https://serp-cache.synapcart.internal/search?${sorted}`);
}

async function cacheGet(key: Request): Promise<Product[] | null> {
  try {
    const hit = await caches.default.match(key);
    return hit ? ((await hit.json()) as Product[]) : null;
  } catch {
    return null;
  }
}

async function cachePut(key: Request, products: Product[]): Promise<void> {
  try {
    await caches.default.put(
      key,
      new Response(JSON.stringify(products), {
        headers: { "Content-Type": "application/json", "Cache-Control": `max-age=${CACHE_TTL_SECONDS}` },
      }),
    );
  } catch {
    // The cache is best-effort.
  }
}

export async function searchProducts(
  env: Env,
  query: string,
  language: string | null,
  currency: string | null,
  limit: number,
): Promise<Product[]> {
  const params = getSerpParams(query, language, currency);
  const key = cacheKey(params);
  const useCache = !settings(env).isTest;
  let products = useCache ? await cacheGet(key) : null;
  if (!products) {
    let data: any;
    try {
      const url = `${SERP_URL}?${new URLSearchParams({ ...params, api_key: env.SERP_API_KEY })}`;
      const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (e) {
      throw new SearchError(`SerpAPI request failed: ${(e as Error).message}`);
    }
    if (data?.error) {
      // "Google hasn't returned any results" is a valid empty result.
      if (String(data.error).includes("hasn't returned any results")) data = {};
      else throw new SearchError("SerpAPI returned an error");
    }
    products = ((data.shopping_results ?? []) as unknown[]).map(clean).filter((p): p is Product => p !== null);
    if (useCache) await cachePut(key, products);
  }
  return products.slice(0, limit);
}
