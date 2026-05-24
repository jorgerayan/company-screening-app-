import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.database import Base


class EvidenceType(str, enum.Enum):
    VERIFIED_FACT = "verified_fact"
    REASONABLE_INFERENCE = "reasonable_inference"
    UNVERIFIABLE = "unverifiable"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(Base):
    """
    Individual structured fact extracted from a source.
    Each finding carries full trazabilidad: which source produced it,
    whether it is a verified fact, an inference, or unverifiable.
    """

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True
    )
    # e.g. "founding_year", "employee_count", "registered_address"
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_value: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        SAEnum(EvidenceType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=EvidenceType.UNVERIFIABLE,
    )
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        SAEnum(ConfidenceLevel, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ConfidenceLevel.LOW,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    analysis: Mapped["Analysis"] = relationship(  # type: ignore[name-defined]
        "Analysis", back_populates="findings"
    )
    source: Mapped[Optional["Source"]] = relationship(  # type: ignore[name-defined]
        "Source", back_populates="findings"
    )
