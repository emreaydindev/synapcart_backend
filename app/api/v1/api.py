from fastapi import APIRouter
from app.api.v1.endpoints import chat, auth, favorites, profiles

api_router = APIRouter()

api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
api_router.include_router(profiles.router, prefix="/user", tags=["user"])

@api_router.get("/health")
async def health_check():
    return {"status": "ok", "service": "v1_api"}