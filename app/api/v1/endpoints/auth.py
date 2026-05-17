from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, Token, PasswordResetRequest, PasswordReset
from app.core.security import get_password_hash, verify_password, create_access_token, generate_reset_token, send_reset_email

router = APIRouter()

@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):

    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(status_code=400, detail="Bu email zaten kayıtlı.")
    
    new_user = User(
        full_name=user_in.name,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=Token)
def login(user_in: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_in.email).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Hatalı email veya şifre.")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/forgot-password")
async def forgot_password(
    request: PasswordResetRequest, 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == request.email).first()
    
    if not user:
        return {"message": "Bu email adresiyle ilişkili bir hesap varsa, şifre sıfırlama linki göndereceğiz."}    

    reset_token = generate_reset_token()
    user.reset_token = reset_token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    
    db.add(user)
    db.commit()
    
    try:
        await send_reset_email(
            email=user.email,
            token=reset_token
        )
    except Exception as e:
        print(e)
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail="Email gönderme başarısız, daha sonra deneyin"
        )
    
    return {"message": "Bu email adresiyle ilişkili bir hesap varsa, şifre sıfırlama linki göndereceğiz."}   

@router.post("/reset-password")
async def reset_password(
    request: PasswordReset,
    db: Session = Depends(get_db)
):    
    user = db.query(User).filter(
        User.reset_token == request.token
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Geçersiz şifre sıfırlama linki"
        )
    
    if user.reset_token_expires is None or datetime.utcnow() > user.reset_token_expires:
        user.reset_token = None
        user.reset_token_expires = None
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Şifre sıfırlama linki süresi dolmuş"
        )
    
    user.hashed_password = get_password_hash(request.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    
    db.add(user)
    db.commit()
    
    return {"message": "Şifreniz başarıyla sıfırlandı"}