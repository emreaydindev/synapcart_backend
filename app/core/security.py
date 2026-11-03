import hashlib
import secrets
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

import bcrypt
from jose import jwt

from app.core.config import settings
from app.core.database import utcnow

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

# bcrypt only looks at the first 72 bytes; bcrypt>=5 raises for longer input.
BCRYPT_MAX_BYTES = 72


def get_password_hash(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Over-long password or malformed hash.
        return False


def create_access_token(subject: str, token_version: int = 0, expires_delta: Optional[timedelta] = None) -> str:
    expire = utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "tv": token_version, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """Reset tokens are stored hashed so a DB leak can't be used to take over accounts."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_reset_url(token: str) -> str:
    base_url = settings.APP_FRONTEND_URL.rstrip("/")
    return f"{base_url}/reset-password?token={quote(token, safe='')}"
