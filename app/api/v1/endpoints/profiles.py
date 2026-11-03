from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_required
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import AccountDelete, PasswordChange, Token, UserResponse, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserResponse)
def get_my_profile(current_user: User = Depends(get_current_user_required)):
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_profile(
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    update_data = user_update.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_data.items():
        setattr(current_user, key, value)

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/password", response_model=Token)
def change_password(
    body: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Mevcut şifre hatalı.")

    current_user.hashed_password = get_password_hash(body.new_password)
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()

    # Other devices are logged out; this one gets a fresh token.
    return Token(
        access_token=create_access_token(current_user.email, current_user.token_version),
        token_type="bearer",
        user_name=current_user.full_name,
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: Optional[AccountDelete] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    # Password confirmation is optional for backwards compatibility with
    # app versions that send no body; when given, it must be correct.
    if body and body.password is not None and not verify_password(body.password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Şifre hatalı.")

    db.delete(current_user)
    db.commit()
    return None
