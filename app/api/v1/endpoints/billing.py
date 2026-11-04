import base64
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_required
from app.api.v1.endpoints.profiles import profile_response
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.user import User
from app.schemas.billing import PlayVerifyRequest, PubSubPush
from app.schemas.user import UserResponse
from app.services import billing_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/google/verify", response_model=UserResponse)
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def verify_google_purchase(
    request: Request,
    body: PlayVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Validate a Play subscription purchase and update the plan. Returns the updated profile.

    The app acknowledges the purchase itself after this succeeds.
    """
    if body.product_id not in settings.PLAY_SUBSCRIPTION_IDS:
        raise HTTPException(status_code=400, detail="Bilinmeyen abonelik ürünü.")

    try:
        subscription = await billing_service.fetch_subscription(body.purchase_token)
    except billing_service.BillingNotConfigured:
        raise HTTPException(status_code=503, detail="Ödeme doğrulama şu an kullanılamıyor.")
    except billing_service.InvalidPurchase:
        raise HTTPException(status_code=400, detail="Satın alma doğrulanamadı.")
    except billing_service.BillingError:
        logger.exception("Play verification failed")
        raise HTTPException(status_code=502, detail="Satın alma şu an doğrulanamadı, lütfen tekrar deneyin.")

    # The app passes the user id as obfuscatedAccountId; refuse someone else's purchase.
    account_id = (subscription.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId")
    if account_id and account_id != current_user.id:
        raise HTTPException(status_code=409, detail="Bu abonelik başka bir hesaba ait.")
    owner = billing_service.find_user_for_token(db, body.purchase_token)
    if owner is not None and owner.id != current_user.id:
        raise HTTPException(status_code=409, detail="Bu abonelik başka bir hesaba ait.")

    billing_service.apply_subscription(db, current_user, body.purchase_token, subscription)
    return profile_response(db, current_user)


@router.post("/google/rtdn", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def google_rtdn(
    body: PubSubPush,
    token: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Pub/Sub push endpoint for Play Real-time Developer Notifications.

    Configure the push URL as .../billing/google/rtdn?token=<PLAY_RTDN_TOKEN>.
    Any 2xx acks the message; a 5xx makes Pub/Sub retry.
    """
    if not settings.PLAY_RTDN_TOKEN or not hmac.compare_digest(token, settings.PLAY_RTDN_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        payload = json.loads(base64.b64decode(body.message.data or "") or b"{}")
    except ValueError:
        logger.warning("RTDN with undecodable data (id=%s)", body.message.messageId)
        return None

    if payload.get("packageName") and payload["packageName"] != settings.PLAY_PACKAGE_NAME:
        return None

    voided = payload.get("voidedPurchaseNotification")
    if voided and voided.get("purchaseToken"):
        user = billing_service.find_user_for_token(db, voided["purchaseToken"])
        if user:
            billing_service.revoke(db, user)
            logger.info("Purchase voided; plan revoked (user=%s)", user.id)
        return None

    notification = payload.get("subscriptionNotification")
    if not notification or not notification.get("purchaseToken"):
        return None  # testNotification or one-time products

    purchase_token = notification["purchaseToken"]
    try:
        subscription = await billing_service.fetch_subscription(purchase_token)
    except billing_service.InvalidPurchase:
        return None
    except (billing_service.BillingNotConfigured, billing_service.BillingError):
        logger.exception("RTDN: could not fetch subscription")
        raise HTTPException(status_code=503, detail="Unavailable")

    user = billing_service.find_user_for_token(db, purchase_token, subscription)
    if user is None:
        # Not verified by the app yet; /google/verify will pick it up.
        logger.info("RTDN for unknown token (type=%s)", notification.get("notificationType"))
        return None
    billing_service.apply_subscription(db, user, purchase_token, subscription)
    return None
