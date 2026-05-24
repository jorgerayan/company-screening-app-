from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any


class LLMResultResponse(BaseModel):
    id: UUID
    analysis_id: UUID
    module_name: str
    output_payload: Dict[str, Any]
    model_used: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}
