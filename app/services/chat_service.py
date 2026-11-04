import json
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.user import User

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TITLE = "Yeni Sohbet"
HISTORY_MESSAGES = 6
HISTORY_CHARS_PER_MESSAGE = 500


def get_owned_session(db: Session, session_id: int, user: User) -> Optional[ChatSession]:
    return db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == user.id,
    ).first()


def is_session_locked(db: Session, session: ChatSession, max_sessions: Optional[int]) -> bool:
    """A session is locked when the user has `max_sessions` newer ones."""
    if max_sessions is None:
        return False
    newer = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == session.user_id, ChatSession.id > session.id)
        .count()
    )
    return newer >= max_sessions


def load_history(db: Session, session_id: int, limit: int = HISTORY_MESSAGES) -> List[str]:
    """Most recent messages, oldest first, as 'Kullanıcı: ...' / 'Asistan: ...' lines."""
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [
        f"{'Kullanıcı' if m.role == 'user' else 'Asistan'}: {(m.content or '')[:HISTORY_CHARS_PER_MESSAGE]}"
        for m in reversed(rows)
    ]


def save_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    products: Optional[List[dict]] = None,
) -> Optional[ChatMessage]:
    try:
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            products=json.dumps(products, ensure_ascii=False) if products else None,
        )
        db.add(message)

        if role == "user":
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session and (session.title == DEFAULT_SESSION_TITLE or session.title is None):
                session.title = (content[:30] + "...") if len(content) > 30 else content

        db.commit()
        db.refresh(message)
        return message
    except Exception:
        db.rollback()
        logger.exception("Failed to save chat message")
        return None
