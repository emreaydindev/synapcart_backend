import logging
import time
from collections import OrderedDict
from typing import List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SERP_URL = "https://serpapi.com/search"

_LANG_MAP = {
    "tr": {"hl": "tr", "gl": "tr", "location": "Turkey"},
    "en": {"hl": "en", "gl": "us", "location": "United States"},
    "ar": {"hl": "ar", "gl": "sa", "location": "Saudi Arabia"},
    "ru": {"hl": "ru", "gl": "ru", "location": "Russian Federation"},
    "fr": {"hl": "fr", "gl": "fr", "location": "France"},
    "de": {"hl": "de", "gl": "de", "location": "Germany"},
    "es": {"hl": "es", "gl": "es", "location": "Spain"},
    "it": {"hl": "it", "gl": "it", "location": "Italy"},
    "zh": {"hl": "zh-cn", "gl": "cn", "location": "China"},
    "ja": {"hl": "ja", "gl": "jp", "location": "Japan"},
}


class SearchError(Exception):
    pass


def get_serp_params(query: str, language: Optional[str] = "tr", currency: Optional[str] = "TRY") -> dict:
    lang = (language or "tr").lower()
    params = {"engine": "google_shopping", "q": query, **_LANG_MAP.get(lang, _LANG_MAP["tr"])}

    if currency == "TRY":
        params.update(gl="tr", location="Turkey")
    elif currency == "EUR" and lang not in ("fr", "de", "es", "it"):
        params.update(gl="de", location="Germany")
    elif currency == "USD" and lang != "en":
        params.update(gl="us", location="United States")
    elif currency == "GBP":
        params.update(gl="uk", location="United Kingdom")

    return params


# Small in-process TTL cache: identical searches within the window reuse results
# instead of paying for another SerpAPI call.
_CACHE_TTL_SECONDS = 30 * 60
_CACHE_MAX = 256
_cache: "OrderedDict[Tuple, Tuple[float, List[dict]]]" = OrderedDict()


def _cache_get(key: Tuple) -> Optional[List[dict]]:
    hit = _cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.monotonic() - ts > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return value


def _cache_put(key: Tuple, value: List[dict]) -> None:
    _cache[key] = (time.monotonic(), value)
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def _clean(item: dict) -> Optional[dict]:
    link = item.get("product_link") or item.get("link")
    title = item.get("title")
    if not link or not title:
        return None
    return {
        "title": title,
        "price": item.get("extracted_price"),
        "source": item.get("source"),
        "link": link,
        "thumbnail": item.get("thumbnail"),
    }


async def search_products(query: str, language: Optional[str], currency: Optional[str], limit: int) -> List[dict]:
    params = get_serp_params(query, language, currency)
    key = tuple(sorted(params.items()))

    products = _cache_get(key)
    if products is None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(SERP_URL, params={**params, "api_key": settings.SERP_API_KEY})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SearchError(f"SerpAPI request failed: {type(e).__name__}") from e

        if data.get("error"):
            # "Google hasn't returned any results" is a valid empty result.
            if "hasn't returned any results" in str(data["error"]):
                data = {}
            else:
                raise SearchError("SerpAPI returned an error")

        products = [p for p in (_clean(i) for i in data.get("shopping_results", [])) if p]
        _cache_put(key, products)

    return products[:limit]
