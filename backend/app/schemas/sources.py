from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.models.source import SourceType, SourceStatus


class SourceResponse(BaseModel):
    id: UUID
    analysis_id: UUID
    source_type: SourceType
    url: Optional[str] = None
    title: Optional[str] = None
    fetched_at: datetime
    status: SourceStatus

    model_config = {"from_attributes": True}
