import uuid
from datetime import datetime
from typing import List
from sqlalchemy import DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.database import Base


class PriorityRating(str, enum.Enum):
    HIGH = "high"
    INTERESTING_WITH_DOUBTS = "interesting_with_doubts"
    LOW = "low"
    INSUFFICIENT_DATA = "insufficient_data"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), unique=True, nullable=False
    )
    factual_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    business_model: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    traction_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    references: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    conclusion: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    management: Mapped[dict] = mapped_column(JSONB, nullable=True, default=dict)
    competitive_position: Mapped[dict] = mapped_column(JSONB, nullable=True, default=dict)
    operational_signals: Mapped[dict] = mapped_column(JSONB, nullable=True, default=dict)
    corporate_structure: Mapped[dict] = mapped_column(JSONB, nullable=True, default=dict)
    executive_summary: Mapped[dict] = mapped_column(JSONB, nullable=True, default=None)
    priority_rating: Mapped[PriorityRating] = mapped_column(
        SAEnum(PriorityRating, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    analysis: Mapped["Analysis"] = relationship(
        "Analysis", back_populates="report"
    )