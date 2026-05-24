from pydantic import BaseModel, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, Any, List, Dict
from app.models.report import PriorityRating


class RiskItem(BaseModel):
    name: str
    severity: str  # high | medium | low
    evidence: str
    explanation: str
    what_to_validate: str
    evidence_type: str  # verified_fact | reasonable_inference | unverifiable

    @field_validator("what_to_validate", mode="before")
    @classmethod
    def normalize_what_to_validate(cls, v: Any) -> str:
        """Old Gemini runs (pre-JSON-mode) stored what_to_validate as a list[str].
        New runs with response_mime_type='application/json' correctly return a str.
        Normalize list → str so both formats deserialize without ValidationError.
        """
        if isinstance(v, list):
            return " ".join(str(item).strip() for item in v if item)
        return v


class ReportResponse(BaseModel):
    report_id: UUID
    analysis_id: UUID
    company_name: str
    website_url: str
    factual_profile: Dict[str, Any]
    business_model: Dict[str, Any]
    traction_signals: Dict[str, Any]
    risks: List[RiskItem]
    references: Dict[str, Any]
    conclusion: Dict[str, Any]
    management: Optional[Dict[str, Any]] = None
    competitive_position: Optional[Dict[str, Any]] = None
    operational_signals: Optional[Dict[str, Any]] = None
    corporate_structure: Optional[Dict[str, Any]] = None
    executive_summary: Optional[Dict[str, Any]] = None
    priority_rating: PriorityRating
    generated_at: datetime

    model_config = {"from_attributes": True}
