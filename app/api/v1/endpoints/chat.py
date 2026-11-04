import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_required, require_premium, require_quota
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.errors import history_locked
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.schemas.chat import (
    AgentResponse,
    ChatRequest,
    CompareItem,
    CompareRequest,
    CompareResponse,
    MessageResponse,
    SessionResponse,
    SessionUpdate,
)
from app.services import gemini_service, plan_service
from app.services.plan_service import PlanLimits
from app.services.agent_service import ERROR_MESSAGES, AgentState, app_agent, localized, stream_agent
from app.services.chat_service import (
    DEFAULT_SESSION_TITLE,
    get_owned_session,
    is_session_locked,
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


def _require_unlocked(db: Session, session: ChatSession, limits: PlanLimits) -> None:
    if is_session_locked(db, session, limits.max_sessions):
        raise history_locked()


def _initial_state(db: Session, session_id: int, user: User, question: str, limits: PlanLimits) -> AgentState:
    # History is loaded *before* the new message is saved so it isn't duplicated.
    return {
        "question": question,
        "history": load_history(db, session_id),
        "user_name": user.full_name or "",
        "language": user.language or "tr",
        "currency": user.currency or "TRY",
        "max_products": limits.max_products,
        "analyst_model": limits.analyst_model,
    }


def _start_agent_turn(db: Session, session_id: int, user: User, message: str, limits: PlanLimits) -> AgentState:
    """Shared by both agent routes: ownership, history lock, quota, then save the question."""
    session = _require_session(db, session_id, user)
    _require_unlocked(db, session, limits)
    state = _initial_state(db, session_id, user, message, limits)
    plan_service.record_message(db, user)
    save_message(db, session_id, "user", message)
    return state


# --- Sessions ---

@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    """Newest first. On the free plan, sessions past the most recent 10 are `locked`."""
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.id.desc())
        .all()
    )
    max_sessions = plan_service.get_limits(current_user).max_sessions
    return [
        SessionResponse.model_validate(s).model_copy(
            update={"locked": max_sessions is not None and i >= max_sessions}
        )
        for i, s in enumerate(sessions)
    ]


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
    session = _require_session(db, session_id, current_user)
    _require_unlocked(db, session, plan_service.get_limits(current_user))
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
    limits: PlanLimits = Depends(require_quota),
):
    state = _start_agent_turn(db, session_id, current_user, body.message, limits)

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
    limits: PlanLimits = Depends(require_quota),
):
    state = _start_agent_turn(db, session_id, current_user, body.message, limits)
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


# --- Comparison (premium) ---

COMPARE_ERROR = {
    "tr": "Karşılaştırma şu an yapılamadı, lütfen birazdan tekrar dene.",
    "en": "The comparison couldn't be made right now, please try again shortly.",
}


@router.post("/compare", response_model=CompareResponse)
@limiter.limit(settings.AGENT_RATE_LIMIT, key_func=user_or_ip_key)
async def compare_products(
    request: Request,
    body: CompareRequest,
    current_user: User = Depends(require_premium),
):
    """Structured pros/cons per product plus a verdict, in the user's language."""
    products = [p.model_dump() for p in body.products]
    limits = plan_service.get_limits(current_user)
    try:
        data = await gemini_service.compare_products(
            products,
            currency=current_user.currency or "TRY",
            language=current_user.language or "tr",
            model_name=limits.analyst_model,
        )
    except gemini_service.GeminiError:
        logger.exception("Comparison failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=localized(COMPARE_ERROR, current_user.language),
        )

    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    items = []
    # One item per requested product, in order, even if the model returned fewer.
    for i, product in enumerate(products):
        raw = raw_items[i] if i < len(raw_items) and isinstance(raw_items[i], dict) else {}
        items.append(
            CompareItem(
                title=product["title"],
                link=product.get("link"),
                pros=[str(x) for x in (raw.get("pros") or []) if x][:4],
                cons=[str(x) for x in (raw.get("cons") or []) if x][:3],
            )
        )
    best = data.get("best_index")
    best = best if isinstance(best, int) and 0 <= best < len(products) else None
    return CompareResponse(items=items, verdict=str(data.get("verdict") or ""), best_index=best)
