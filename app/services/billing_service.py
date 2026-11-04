"""Google Play subscription verification (purchases.subscriptionsv2)."""
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.models.user import User
from app.services import google_auth
from app.services.plan_service import PLAN_FREE, PLAN_PREMIUM

logger = logging.getLogger(__name__)

API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"

# States that still grant access until `expiryTime`.
ENTITLED_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    "SUBSCRIPTION_STATE_CANCELED",  # cancelled but not yet expired
}


class BillingNotConfigured(Exception):
    pass


class BillingError(Exception):
    """Google API unreachable or returned an unexpected error."""


class InvalidPurchase(Exception):
    """The token is unknown to Google or doesn't belong to this app/product."""


def _account() -> dict:
    account = google_auth.load_service_account(settings.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON)
    if not account:
        raise BillingNotConfigured()
    return account


async def fetch_subscription(purchase_token: str) -> dict:
    """GET purchases.subscriptionsv2 for the token. Raises InvalidPurchase on 400/404/410."""
    try:
        token = await google_auth.access_token(_account(), google_auth.SCOPE_ANDROID_PUBLISHER)
    except google_auth.GoogleAuthError as e:
        raise BillingError(str(e)) from e
    url = f"{API}/{settings.PLAY_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{quote(purchase_token, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise BillingError(f"Play API request failed: {type(e).__name__}") from e
    if r.status_code in (400, 404, 410):
        raise InvalidPurchase()
    if r.status_code >= 300:
        raise BillingError(f"Play API returned {r.status_code}")
    return r.json()


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # RFC 3339, e.g. "2026-12-04T10:00:00.123Z"
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def entitlement(subscription: dict) -> tuple[Optional[str], Optional[datetime], bool]:
    """(product_id, expiry, entitled) for our subscription products in a subscriptionsv2 resource."""
    product_id = None
    expiry = None
    for item in subscription.get("lineItems") or []:
        if item.get("productId") not in settings.PLAY_SUBSCRIPTION_IDS:
            continue
        item_expiry = _parse_time(item.get("expiryTime"))
        if expiry is None or (item_expiry and item_expiry > expiry):
            product_id, expiry = item.get("productId"), item_expiry
    entitled = (
        product_id is not None
        and subscription.get("subscriptionState") in ENTITLED_STATES
        and expiry is not None
        and expiry > utcnow()
    )
    return product_id, expiry, entitled


def apply_subscription(db: Session, user: User, purchase_token: str, subscription: dict) -> bool:
    """Update the user's plan from a Play subscription; returns whether premium is active."""
    product_id, expiry, entitled = entitlement(subscription)

    # A resubscribe/upgrade replaces the old token (linkedPurchaseToken).
    user.play_purchase_token = purchase_token
    user.play_product_id = product_id
    user.plan_expires_at = expiry
    user.plan = PLAN_PREMIUM if entitled else PLAN_FREE
    db.commit()
    db.refresh(user)
    logger.info("Plan updated from Play (user=%s, state=%s, entitled=%s)", user.id,
                subscription.get("subscriptionState"), entitled)
    return entitled


def find_user_for_token(db: Session, purchase_token: str, subscription: Optional[dict] = None) -> Optional[User]:
    user = db.query(User).filter(User.play_purchase_token == purchase_token).first()
    if user is None and subscription:
        linked = subscription.get("linkedPurchaseToken")
        if linked:
            user = db.query(User).filter(User.play_purchase_token == linked).first()
        if user is None:
            account_id = (subscription.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId")
            if account_id:
                user = db.get(User, account_id)
    return user


def revoke(db: Session, user: User) -> None:
    user.plan = PLAN_FREE
    user.plan_expires_at = None
    db.commit()
