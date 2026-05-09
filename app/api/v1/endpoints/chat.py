from fastapi import APIRouter, HTTPException
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
async def chat_with_agent(request: ChatRequest):
    try:
        
        initial_state = {
            "messages": [request.message],
            "products": [],
            "analysis": ""
        }
        
        result = await app_agent.ainvoke(initial_state)
        
        return {
            "bot_response": result["analysis"],
            "found_products": result["products"],
            "steps_taken": result["messages"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))