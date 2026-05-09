from fastapi import APIRouter
# İleride buraya oluşturacağın endpointleri import edeceksin
# from app.api.v1.endpoints import products, chat

api_router = APIRouter()

# Örnek bir test endpoint'i ekleyelim
@api_router.get("/health")
async def health_check():
    return {"status": "ok", "service": "v1_api"}