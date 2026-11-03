import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_user_by_email
from app.core.config import settings
from app.core.database import get_db, utcnow
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    generate_reset_token,
    get_password_hash,
    hash_reset_token,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    PasswordReset,
    PasswordResetRequest,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.email_service import send_reset_email

logger = logging.getLogger(__name__)
router = APIRouter()

FORGOT_PASSWORD_MESSAGE = "Bu email adresiyle ilişkili bir hesap varsa, şifre sıfırlama linki göndereceğiz."
# Minimum gap between two reset emails for the same account.
RESET_EMAIL_COOLDOWN = timedelta(minutes=2)


def _issue_token(user: User) -> Token:
    return Token(
        access_token=create_access_token(user.email, user.token_version or 0),
        token_type="bearer",
        user_name=user.full_name,
    )


def _authenticate(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Hatalı email veya şifre.")
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, user_in: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_email(db, user_in.email):
        raise HTTPException(status_code=400, detail="Bu email zaten kayıtlı.")

    new_user = User(
        full_name=user_in.name,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, user_in: UserLogin, db: Session = Depends(get_db)):
    return _issue_token(_authenticate(db, user_in.email, user_in.password))


@router.post("/token", response_model=Token, include_in_schema=not settings.is_prod)
@limiter.limit("10/minute")
def login_form(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 form login so the Swagger "Authorize" button works."""
    return _issue_token(_authenticate(db, form.username, form.password))


@router.post("/forgot-password")
@limiter.limit("5/hour")
async def forgot_password(request: Request, body: PasswordResetRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, body.email)
    if not user:
        return {"message": FORGOT_PASSWORD_MESSAGE}

    now = utcnow()
    expire_delta = timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)
    if user.reset_token_expires and (user.reset_token_expires - expire_delta) > now - RESET_EMAIL_COOLDOWN:
        # A link was sent moments ago; don't spam the inbox.
        return {"message": FORGOT_PASSWORD_MESSAGE}

    raw_token = generate_reset_token()
    user.reset_token = hash_reset_token(raw_token)
    user.reset_token_expires = now + expire_delta
    db.commit()

    try:
        await send_reset_email(email=user.email, token=raw_token)
    except Exception:
        logger.exception("Failed to send password reset email")
        user.reset_token = None
        user.reset_token_expires = None
        db.commit()
        # Same response as for unknown emails so accounts can't be enumerated.

    return {"message": FORGOT_PASSWORD_MESSAGE}


@router.post("/reset-password")
@limiter.limit("10/hour")
def reset_password(request: Request, body: PasswordReset, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == hash_reset_token(body.token)).first()
    if not user:
        raise HTTPException(status_code=400, detail="Geçersiz şifre sıfırlama linki.")

    if user.reset_token_expires is None or utcnow() > user.reset_token_expires:
        user.reset_token = None
        user.reset_token_expires = None
        db.commit()
        raise HTTPException(status_code=400, detail="Şifre sıfırlama linkinin süresi dolmuş.")

    user.hashed_password = get_password_hash(body.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    user.token_version = (user.token_version or 0) + 1
    db.commit()

    return {"message": "Şifreniz başarıyla sıfırlandı."}
