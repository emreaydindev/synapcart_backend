from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.endpoints import auth, billing, chat, favorites, profiles
from app.core.database import get_db

api_router = APIRouter()

api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
api_router.include_router(profiles.router, prefix="/user", tags=["user"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])


@api_router.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable"})
    return {"status": "ok", "service": "v1_api", "database": "ok"}
