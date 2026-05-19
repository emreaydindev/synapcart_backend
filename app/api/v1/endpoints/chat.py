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

@router.get("/agent/{session_id}/messages")
def get_session_messages(session_id: int, db: Session = Depends(get_db)):
    return db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc()).all()

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
        raise HTTPException(status_code=404, detail="Oturum bulunamadı.")

    # 1. Kullanıcı mesajını kaydet (Ajan çalışmadan önce)
    save_message(db, session_id, "user", request.message)

    # 2. Geçmişi yükle
    past_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.desc()).limit(6).all()
    
    history = [f"{'Kullanıcı' if m.role == 'user' else 'Asistan'}: {m.content}" for m in reversed(past_messages)]
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
        
        # 3. Asistan cevabını kaydet
        save_message(db, session_id, "assistant", result.get("analysis", ""))

        if "user_object" in result:
            del result["user_object"]
            
        return result

    except Exception as e:
        print(f"Agent Error: {str(e)}")
        save_message(db, session_id, "assistant", "Üzgünüm, şu an cevap veremiyorum.")
        raise HTTPException(status_code=500, detail="Ajan işlemi başarısız.")

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
        raise HTTPException(status_code=404, detail="Oturum bulunamadı.")

    # 1. Kullanıcı mesajını kaydet
    save_message(db, session_id, "user", request.message)

    # 2. Geçmişi yükle
    past_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.desc()).limit(6).all()

    history = [f"{'Kullanıcı' if m.role == 'user' else 'Asistan'}: {m.content}" for m in reversed(past_messages)]
    history.append(request.message)

    initial_state = {
        "messages": history,
        "user_object": current_user,
        "products": [],
        "analysis": "",
        "status": "searching"
    }

    async def event_generator():
        full_analysis = ""
        try:
            async for partial in stream_agent_invoke(initial_state):
                # Analysis kısmını biriktir
                if partial.get("analysis"):
                    full_analysis += partial["analysis"]
                
                yield f"data: {json.dumps(partial, default=str)}\n\n"
            
            # 3. İşlem bitince asistan cevabını kaydet
            if full_analysis:
                save_message(db, session_id, "assistant", full_analysis)
                
            await asyncio.sleep(0)
        except Exception as e:
            print(f"Streaming Error: {str(e)}")
            save_message(db, session_id, "assistant", "Hata oluştu.")
            yield f"data: {json.dumps({'status': 'error', 'analysis': 'Bağlantı hatası'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")