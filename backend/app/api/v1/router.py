from fastapi import APIRouter
from app.api.v1 import analysis

router = APIRouter(prefix="/api/v1")
router.include_router(analysis.router)