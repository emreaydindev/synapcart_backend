from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ALGORITHM, SECRET_KEY
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token", auto_error=False)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()


def get_current_user_optional(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    email = payload.get("sub")
    if not email:
        return None

    user = get_user_by_email(db, email)
    if user is None:
        return None

    # Tokens issued before the last password change are revoked.
    if int(payload.get("tv", 0)) != (user.token_version or 0):
        return None

    return user


def get_current_user_required(
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturumunuzun süresi doldu. Lütfen tekrar giriş yapın.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
