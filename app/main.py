from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.core.database import engine, Base
from app.models import user, favorite, chat

app = FastAPI(
    title="SynapCart AI Backend",
    description="Agentic Shopping Assistant API powered by Gemini",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For Development Phase
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
Base.metadata.create_all(bind=engine)

@app.get("/")
async def root():
    return {"message": "SynapCart API is running", "status": "active"}