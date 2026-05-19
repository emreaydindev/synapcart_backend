from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user_required
from app.models.user import User
from app.models.chat import ChatSession, ChatMessage
from app.services.agent_service import app_agent
from pydantic import BaseModel

from app.services.chat_service import save_message

from fastapi.responses import StreamingResponse
import json
import asyncio

from app.services.agent_service import stream_agent_invoke

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

@router.post("/agent/{session_id}")
async def chat_with_agent(
    session_id: int,
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, 
        ChatSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Sohbet oturumu bulunamadı veya bu oturuma erişim yetkiniz yok."
        )

    past_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.desc()).limit(6).all()
    
    history = []
    for m in reversed(past_messages):
        role_label = "Kullanıcı" if m.role == "user" else "Asistan"
        history.append(f"{role_label}: {m.content}")

    history.append(request.message)

    initial_state = {
        "messages": history,
        "user_object": current_user,
        "products": [],
        "analysis": "",
        "status": "searching"
    }

    try:
        result = await app_agent.ainvoke(initial_state)
        
        save_message(db, session_id, "user", request.message)
        save_message(db, session_id, "assistant", result["analysis"])

        if "user_object" in result:
            del result["user_object"]
            
        return result

    except Exception as e:
        print(f"Agent Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Ajan işlemi sırasında bir hata oluştu."
        )
    
@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    return db.query(ChatSession).filter(ChatSession.user_id == current_user.id).all()

@router.post("/sessions")
def create_session(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    new_session = ChatSession(user_id=current_user.id, title="Yeni Sohbet")
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return new_session

@router.post("/agent/{session_id}/stream")
async def stream_chat_with_agent(
    session_id: int,
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id
    ).first()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sohbet oturumu bulunamadı veya bu oturuma erişim yetkiniz yok.")

    past_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.desc()).limit(6).all()

    history = []
    for m in reversed(past_messages):
        role_label = "Kullanıcı" if m.role == "user" else "Asistan"
        history.append(f"{role_label}: {m.content}")

    history.append(request.message)

    initial_state = {
        "messages": history,
        "user_object": current_user,
        "products": [],
        "analysis": "",
        "status": "searching"
    }

    async def event_generator():
        try:
            async for partial in stream_agent_invoke(initial_state):
                yield f"data: {json.dumps(partial, default=str)}\n\n"
            await asyncio.sleep(0)
        except Exception as e:
            print(f"Streaming Agent Error: {str(e)}")
            err = {
                "status": "error", 
                "analysis": f"Bağlantı hatası oluştu: {str(e)}",
                "products": []
            }
            yield f"data: {json.dumps(err)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")