import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.errors import CodedError
from app.core.logging import setup_logging
from app.core.rate_limit import limiter

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.AUTO_MIGRATE:
        from app.db.migrate import run_migrations

        run_migrations()
    yield


app = FastAPI(
    title="SynapCart AI Backend",
    description="Agentic Shopping Assistant API powered by Gemini",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None if settings.is_prod else "/redoc",
    openapi_url=None if settings.is_prod else "/openapi.json",
)

app.state.limiter = limiter

# Mobile clients don't need CORS; this only governs browsers. Auth is a bearer
# header (no cookies), so credentials are not allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Çok fazla istek gönderdiniz. Lütfen biraz bekleyip tekrar deneyin.", "code": "rate_limited"},
    )


@app.exception_handler(CodedError)
async def coded_error_handler(request: Request, exc: CodedError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # Clients (Android/web) expect `detail` to be a single readable string.
    errors = exc.errors()
    message = "Geçersiz istek."
    if errors:
        msg = str(errors[0].get("msg", ""))
        if msg.startswith("Value error, "):
            message = msg[len("Value error, "):]
        else:
            field = ".".join(str(p) for p in errors[0].get("loc", [])[1:])
            message = f"Geçersiz alan: {field}" if field else message
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": message, "errors": jsonable_errors(errors)},
    )


def jsonable_errors(errors):
    return [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", ""))} for e in errors]


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin."},
    )


app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "SynapCart API is running", "status": "active"}
