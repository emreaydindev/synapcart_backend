from sqlalchemy.orm import Session
from app.models.chat import ChatMessage, ChatSession

def save_message(db: Session, session_id: int, role: str, content: str):
    try:
        new_message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content
        )
        db.add(new_message)
        
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session and (session.title == "Yeni Sohbet" or session.title is None):
            session.title = (content[:30] + "...") if len(content) > 30 else content
        
        db.commit()
        db.refresh(new_message)
        print(f"Başarıyla kaydedildi: {role} - {content[:20]}...")
        return new_message
    except Exception as e:
        db.rollback()
        print(f"HATA: Mesaj kaydedilemedi: {e}")
        return None