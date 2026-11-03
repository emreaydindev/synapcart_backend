from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def user_or_ip_key(request: Request) -> str:
    """Rate-limit key: the JWT subject when present, otherwise the client IP."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = jwt.decode(auth[7:], settings.SECRET_KEY, algorithms=["HS256"])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except JWTError:
            pass
    return get_remote_address(request)


# In-memory storage: fine for a single instance. Point `storage_uri` at Redis
# before scaling to multiple workers/instances.
limiter = Limiter(key_func=get_remote_address, enabled=settings.ENV != "test")
