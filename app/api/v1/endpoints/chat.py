from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import get_current_user_optional
from app.models.user import User
from app.services.gemini_service import get_chat_response
from app.services.agent_service import app_agent
from pydantic import BaseModel

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

@router.post("/gemini")
async def chat_with_ai(request: ChatRequest):
    try:
        response = await get_chat_response(request.message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agent")
async def chat_with_agent(
    request: ChatRequest,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    user_status = f"User: {current_user.email}" if current_user else "Guest Session"
    print(f"--- Chat started by {user_status} ---")

    initial_state = {
        "messages": [request.message],
        "products": [],
        "analysis": ""
    }
    
    result = await app_agent.ainvoke(initial_state)
    
    # TODO: Eğer current_user varsa, bu chat veri tabanına kaydedilebilir.
    
    return {
        "bot_response": result["analysis"],
        "found_products": result["products"],
        "is_logged_in": current_user is not None
    }