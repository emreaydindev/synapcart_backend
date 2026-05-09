from fastapi import FastAPI
from app.api.v1.api import api_router

app = FastAPI(
    title="SynapCart AI Backend",
    description="Agentic Shopping Assistant API powered by Gemini",
    version="1.0.0"
)

# Router entegrasyonu
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "SynapCart API is running", "status": "active"}