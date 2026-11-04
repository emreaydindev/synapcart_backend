"""Plans, limits and the daily message quota.

The limits here are mirrored on the web landing page (synapcart_web/lib/site.ts
`plans`) and in the mobile paywall copy; change them together.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.models.usage import UsageDaily
from app.models.user import User
from app.services import gemini_service

PLAN_FREE = "free"
PLAN_PREMIUM = "premium"


@dataclass(frozen=True)
class PlanLimits:
    plan: str
    daily_messages: int
    max_products: int
    analyst_model: str
    max_sessions: Optional[int]  # None = unlimited history
    compare: bool
    price_alerts: bool


def _limits(plan: str) -> PlanLimits:
    if plan == PLAN_PREMIUM:
        return PlanLimits(
            plan=PLAN_PREMIUM,
            daily_messages=100,  # soft cap against abuse
            max_products=8,
            analyst_model=settings.PREMIUM_ANALYST_MODEL,
            max_sessions=None,
            compare=True,
            price_alerts=True,
        )
    return PlanLimits(
        plan=PLAN_FREE,
        daily_messages=5,
        max_products=3,
        analyst_model=gemini_service.DEFAULT_MODEL,
        max_sessions=10,
        compare=False,
        price_alerts=False,
    )


FREE = _limits(PLAN_FREE)


def effective_plan(user: User, now: Optional[datetime] = None) -> str:
    """Premium only while it hasn't expired; a missing expiry means a manual grant."""
    if user.plan != PLAN_PREMIUM:
        return PLAN_FREE
    if user.plan_expires_at is not None and user.plan_expires_at <= (now or utcnow()):
        return PLAN_FREE
    return PLAN_PREMIUM


def get_limits(user: User) -> PlanLimits:
    return _limits(effective_plan(user))


def is_premium(user: User) -> bool:
    return effective_plan(user) == PLAN_PREMIUM


def today() -> date:
    """Quotas reset at 00:00 UTC."""
    return utcnow().date()


def usage_today(db: Session, user: User) -> int:
    row = db.get(UsageDaily, (user.id, today()))
    return row.messages if row else 0


def record_message(db: Session, user: User) -> int:
    """Count one agent message for today; returns the new total."""
    day = today()
    for _ in range(2):
        row = db.get(UsageDaily, (user.id, day))
        if row is None:
            row = UsageDaily(user_id=user.id, date=day, messages=1)
            db.add(row)
        else:
            row.messages = UsageDaily.messages + 1
        try:
            db.commit()
        except IntegrityError:
            # Another request created today's row first; retry as an update.
            db.rollback()
            continue
        db.refresh(row)
        return row.messages
    return usage_today(db, user)
