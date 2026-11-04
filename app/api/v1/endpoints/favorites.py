from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_required, require_premium
from app.core.database import get_db
from app.models.favorite import Favorite
from app.models.user import User
from app.schemas.favorite import FavoriteCreate, FavoriteResponse, FavoriteUpdate

router = APIRouter()


@router.post("/", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
def add_to_favorites(
    favorite_in: FavoriteCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Idempotent: adding an already-saved link returns the existing favorite (200)."""
    existing = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.link == favorite_in.link,
    ).first()
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    data = favorite_in.model_dump()
    if not data.get("currency"):
        data["currency"] = current_user.currency
    new_favorite = Favorite(**data, user_id=current_user.id)
    db.add(new_favorite)
    try:
        db.commit()
    except IntegrityError:
        # Raced with a concurrent add of the same link.
        db.rollback()
        response.status_code = status.HTTP_200_OK
        return db.query(Favorite).filter(
            Favorite.user_id == current_user.id,
            Favorite.link == favorite_in.link,
        ).first()
    db.refresh(new_favorite)
    return new_favorite


@router.get("/", response_model=List[FavoriteResponse])
def get_my_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    return (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.id.desc())
        .all()
    )


@router.delete("/by-link", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite_by_link(
    link: str = Query(min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    deleted = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.link == link,
    ).delete()
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Favori ürün bulunamadı.")
    return None


@router.patch("/{favorite_id}", response_model=FavoriteResponse)
def update_favorite(
    favorite_id: int,
    body: FavoriteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Set or clear the price-alert target (premium)."""
    favorite = db.query(Favorite).filter(
        Favorite.id == favorite_id,
        Favorite.user_id == current_user.id,
    ).first()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favori ürün bulunamadı.")

    favorite.target_price = body.target_price
    # A new target re-arms the alert.
    favorite.last_notified_price = None
    db.commit()
    db.refresh(favorite)
    return favorite


@router.delete("/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_favorites(
    favorite_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    favorite = db.query(Favorite).filter(
        Favorite.id == favorite_id,
        Favorite.user_id == current_user.id,
    ).first()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favori ürün bulunamadı.")

    db.delete(favorite)
    db.commit()
    return None
