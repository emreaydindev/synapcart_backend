"""Daily price check for premium users' price alerts.

For every favorite with a `target_price` whose owner is premium, search the
product again (SerpAPI, exact title), find the same offer by link (or by
store + title), store the price, and push an FCM notification when it is at or
below the target. Runs as a Render cron job:

    python -m app.jobs.price_check
"""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal, utcnow
from app.core.logging import setup_logging
from app.models.favorite import Favorite
from app.models.usage import DeviceToken
from app.models.user import User
from app.services import plan_service, push_service
from app.services.search_service import SearchError, search_products

logger = logging.getLogger("app.jobs.price_check")

SEARCH_LIMIT = 20

ALERT_TEXT = {
    "tr": ("Fiyat düştü!", "{title} şimdi {price} ({source}). Hedefin: {target}."),
    "en": ("Price drop!", "{title} is now {price} ({source}). Your target: {target}."),
}


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").lower().split())


def match_offer(favorite: Favorite, results: List[dict]) -> Optional[dict]:
    """The same offer: identical link first, else same store with the same title."""
    for item in results:
        if item.get("link") == favorite.link:
            return item
    for item in results:
        if _norm(item.get("source")) == _norm(favorite.source) and _norm(item.get("title")) == _norm(favorite.title):
            return item
    return None


def _format_price(amount: float, currency: Optional[str]) -> str:
    return f"{amount:,.2f} {currency or ''}".strip()


def should_notify(favorite: Favorite, price: float) -> bool:
    if favorite.target_price is None or price > favorite.target_price:
        return False
    # Notify once per drop: again only if it falls below the last alerted price.
    return favorite.last_notified_price is None or price < favorite.last_notified_price


async def _notify(db: Session, user: User, favorite: Favorite, price: float) -> bool:
    tokens = db.query(DeviceToken).filter(DeviceToken.user_id == user.id).all()
    if not tokens:
        return False
    title, body = ALERT_TEXT.get((user.language or "tr").lower(), ALERT_TEXT["en"])
    body = body.format(
        title=(favorite.title or "")[:60],
        price=_format_price(price, favorite.currency),
        source=favorite.source or "-",
        target=_format_price(favorite.target_price, favorite.currency),
    )
    data = {"type": "price_alert", "favorite_id": str(favorite.id), "link": favorite.link, "price": str(price)}
    sent = False
    for device in tokens:
        try:
            await push_service.send(device.token, title, body, data)
            sent = True
        except push_service.InvalidToken:
            db.delete(device)
        except Exception:
            logger.exception("FCM send failed (user=%s)", user.id)
    db.commit()
    return sent


async def run(db: Session) -> Dict[str, int]:
    stats = {"checked": 0, "matched": 0, "notified": 0, "errors": 0}
    if not push_service.is_configured():
        logger.warning("FCM is not configured; prices are checked but no alerts are sent")

    rows: List[Tuple[Favorite, User]] = (
        db.query(Favorite, User)
        .join(User, Favorite.user_id == User.id)
        .filter(Favorite.target_price.isnot(None), User.plan == plan_service.PLAN_PREMIUM)
        .all()
    )
    for favorite, user in rows:
        if not plan_service.is_premium(user):
            continue  # expired
        stats["checked"] += 1
        try:
            results = await search_products(
                favorite.title, user.language, favorite.currency or user.currency, limit=SEARCH_LIMIT
            )
        except SearchError:
            stats["errors"] += 1
            logger.warning("Price search failed (favorite=%s)", favorite.id)
            continue

        offer = match_offer(favorite, results)
        favorite.last_checked_at = utcnow()
        if not offer or offer.get("price") is None:
            db.commit()
            continue
        stats["matched"] += 1
        price = float(offer["price"])
        favorite.last_checked_price = price
        db.commit()

        if should_notify(favorite, price) and push_service.is_configured():
            if await _notify(db, user, favorite, price):
                favorite.last_notified_price = price
                db.commit()
                stats["notified"] += 1
    return stats


def main() -> None:
    setup_logging()
    with SessionLocal() as db:
        stats = asyncio.run(run(db))
    logger.info("Price check finished: %s", stats)


if __name__ == "__main__":
    main()
