from fastapi import APIRouter, HTTPException
from app.services.gemini_service import get_chat_response
from pydantic import BaseModel

router = APIRouter()

# Basit bir request modeli (schemas/ klasörüne de taşıyabilirsin)
class ChatRequest(BaseModel):
    message: str

@router.post("/")
async def chat_with_ai(request: ChatRequest):
    try:
        # Servis katmanındaki Gemini fonksiyonunu çağırıyoruz
        response = await get_chat_response(request.message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))