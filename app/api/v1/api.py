from fastapi import APIRouter
from app.api.v1.endpoints import chat
# İleride buraya oluşturacağın endpointleri import edeceksin
# from app.api.v1.endpoints import products, chat

api_router = APIRouter()

api_router.include_router(chat.router, prefix="/chat", tags=["chat"])

# Örnek bir test endpoint'i ekleyelim
@api_router.get("/health")
async def health_check():
    return {"status": "ok", "service": "v1_api"}