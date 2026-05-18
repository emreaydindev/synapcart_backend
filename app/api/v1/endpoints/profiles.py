from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user_required
from app.models.user import User
from app.schemas.user import UserUpdate, UserResponse

router = APIRouter()

@router.get("/me", response_model=UserResponse)
def get_my_profile(current_user: User = Depends(get_current_user_required)):
    return current_user

@router.patch("/me", response_model=UserResponse)
def update_profile(
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    update_data = user_update.model_dump(exclude_unset=True)
    
    safe_update_data = {k: v for k, v in update_data.items() if v is not None}
    
    for key, value in safe_update_data.items():
        setattr(current_user, key, value)
    
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    db.delete(current_user)
    db.commit()
    return None