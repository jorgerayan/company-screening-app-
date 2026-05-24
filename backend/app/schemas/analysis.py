from pydantic import BaseModel, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.models.analysis import AnalysisStatus


SUPPORTED_LANGUAGES = {"es", "en", "fr", "de", "it"}


class AnalysisCreateRequest(BaseModel):
    company_name: str
    website_url: str
    country: Optional[str] = None
    sector_hint: Optional[str] = None
    language: Optional[str] = "es"

    @field_validator("company_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("company_name cannot be empty")
        return v.strip()

    @field_validator("website_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("website_url must start with http:// or https://")
        return v.strip()


class AnalysisStatusResponse(BaseModel):
    analysis_id: UUID
    status: AnalysisStatus
    pipeline_step: Optional[str]
    company_name: str
    website_url: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]

    model_config = {"from_attributes": True}


class AnalysisCreateResponse(BaseModel):
    analysis_id: UUID
    status: AnalysisStatus
    message: str