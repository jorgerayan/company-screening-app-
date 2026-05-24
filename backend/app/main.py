from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.router import router
from app.utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="PreAnalysis API",
    description="Business pre-screening platform powered by AI",
    version="0.1.0",
    docs_url="/docs" if settings.environment == "development" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.environment}