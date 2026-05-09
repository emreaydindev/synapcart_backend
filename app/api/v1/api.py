from fastapi import APIRouter
from app.api.v1.endpoints import chat

api_router = APIRouter()

api_router.include_router(chat.router, prefix="/chat", tags=["chat"])

@api_router.get("/health")
async def health_check():
    return {"status": "ok", "service": "v1_api"}