from sqlalchemy.orm import Session
from app.models.chat import ChatMessage, ChatSession

def save_message(db: Session, session_id: int, role: str, content: str):
    
    new_message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content
    )
    db.add(new_message)
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    
    if session and (session.title is None or session.title == "Yeni Sohbet"):
        session.title = content[:30] + ("..." if len(content) > 30 else "")
    
    db.commit()
    db.refresh(new_message)
    return new_message