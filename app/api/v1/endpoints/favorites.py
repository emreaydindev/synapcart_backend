from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user_required
from app.models.user import User
from app.models.favorite import Favorite
from app.schemas.favorite import FavoriteCreate, FavoriteResponse

router = APIRouter()

@router.post("/", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
def add_to_favorites(
    favorite_in: FavoriteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    existing_fav = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.link == favorite_in.link
    ).first()
    
    if existing_fav:
        raise HTTPException(status_code=400, detail="Bu ürün zaten favorilerinizde.")

    new_favorite = Favorite(
        **favorite_in.model_dump(),
        user_id=current_user.id
    )
    
    db.add(new_favorite)
    db.commit()
    db.refresh(new_favorite)
    return new_favorite

@router.get("/", response_model=List[FavoriteResponse])
def get_my_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    return db.query(Favorite).filter(Favorite.user_id == current_user.id).all()

@router.delete("/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_favorites(
    favorite_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    favorite = db.query(Favorite).filter(
        Favorite.id == favorite_id, 
        Favorite.user_id == current_user.id
    ).first()
    
    if not favorite:
        raise HTTPException(status_code=404, detail="Favori ürün bulunamadı.")
        
    db.delete(favorite)
    db.commit()
    return None