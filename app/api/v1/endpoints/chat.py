import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_required
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.schemas.chat import AgentResponse, ChatRequest, MessageResponse, SessionResponse, SessionUpdate
from app.services.agent_service import ERROR_MESSAGES, AgentState, app_agent, localized, stream_agent
from app.services.chat_service import (
    DEFAULT_SESSION_TITLE,
    get_owned_session,
    load_history,
    save_message,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_session(db: Session, session_id: int, user: User) -> ChatSession:
    session = get_owned_session(db, session_id, user)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oturum bulunamadı.")
    return session


def _initial_state(db: Session, session_id: int, user: User, question: str) -> AgentState:
    # History is loaded *before* the new message is saved so it isn't duplicated.
    return {
        "question": question,
        "history": load_history(db, session_id),
        "user_name": user.full_name or "",
        "language": user.language or "tr",
        "currency": user.currency or "TRY",
    }


# --- Sessions ---

@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.id.desc())
        .all()
    )


@router.post("/sessions", response_model=SessionResponse)
def create_session(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    new_session = ChatSession(user_id=current_user.id, title=DEFAULT_SESSION_TITLE)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return new_session


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
def rename_session(
    session_id: int,
    body: SessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    session = _require_session(db, session_id, current_user)
    session.title = body.title.strip()
    db.commit()
    db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    session = _require_session(db, session_id, current_user)
    db.delete(session)
    db.commit()
    return None


@router.get("/agent/{session_id}/messages", response_model=List[MessageResponse])
def get_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    _require_session(db, session_id, current_user)
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )


# --- Agent ---

@router.post("/agent/{session_id}", response_model=AgentResponse)
@limiter.limit(settings.AGENT_RATE_LIMIT, key_func=user_or_ip_key)
async def chat_with_agent(
    request: Request,
    session_id: int,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    _require_session(db, session_id, current_user)
    state = _initial_state(db, session_id, current_user, body.message)
    save_message(db, session_id, "user", body.message)

    try:
        result = await app_agent.ainvoke(state)
    except Exception:
        logger.exception("Agent run failed (session=%s)", session_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=localized(ERROR_MESSAGES, current_user.language),
        )

    analysis = result.get("analysis", "")
    products = result.get("products", []) if result.get("status") == "completed" else []
    save_message(db, session_id, "assistant", analysis, products)
    return AgentResponse(status=result.get("status", "completed"), analysis=analysis, products=products)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post("/agent/{session_id}/stream")
@limiter.limit(settings.AGENT_RATE_LIMIT, key_func=user_or_ip_key)
async def stream_chat_with_agent(
    request: Request,
    session_id: int,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    _require_session(db, session_id, current_user)
    state = _initial_state(db, session_id, current_user, body.message)
    save_message(db, session_id, "user", body.message)
    language = current_user.language

    async def event_generator():
        final = None
        try:
            async for event in stream_agent(state):
                if event["status"] in ("completed", "out_of_scope"):
                    final = event
                yield _sse(event)
        except Exception:
            logger.exception("Agent stream failed (session=%s)", session_id)
            yield _sse({"status": "error", "analysis": localized(ERROR_MESSAGES, language)})
            return

        if final and final.get("analysis"):
            # The request-scoped session may already be closed once the
            # response starts streaming, so use a dedicated one.
            with SessionLocal() as stream_db:
                save_message(stream_db, session_id, "assistant", final["analysis"], final.get("products"))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
