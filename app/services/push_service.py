"""Firebase Cloud Messaging (HTTP v1) for price-alert notifications."""
import logging
from typing import Dict, Optional

import httpx

from app.core.config import settings
from app.services import google_auth

logger = logging.getLogger(__name__)

FCM_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

# Must match the channel the Android app creates.
ANDROID_CHANNEL_ID = "price_alerts"


class PushNotConfigured(Exception):
    pass


class InvalidToken(Exception):
    """The device token is no longer registered; delete it."""


def _account_and_project() -> tuple[dict, str]:
    account = google_auth.load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
    if not account:
        raise PushNotConfigured()
    project = settings.FIREBASE_PROJECT_ID or account.get("project_id")
    if not project:
        raise PushNotConfigured()
    return account, project


def is_configured() -> bool:
    try:
        _account_and_project()
    except (PushNotConfigured, google_auth.GoogleAuthError):
        return False
    return True


async def send(token: str, title: str, body: str, data: Optional[Dict[str, str]] = None) -> None:
    account, project = _account_and_project()
    access = await google_auth.access_token(account, google_auth.SCOPE_FCM)
    message = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in (data or {}).items()},
            "android": {"priority": "high", "notification": {"channel_id": ANDROID_CHANNEL_ID}},
        }
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            FCM_URL.format(project=project),
            json=message,
            headers={"Authorization": f"Bearer {access}"},
        )
    if r.status_code == 404 or "UNREGISTERED" in r.text:
        raise InvalidToken()
    if r.status_code >= 300:
        raise httpx.HTTPStatusError(f"FCM returned {r.status_code}", request=r.request, response=r)
