import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.database import Base


class AnalysisStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        SAEnum(AnalysisStatus, values_callable=lambda x: [e.value for e in x]),
        default=AnalysisStatus.PENDING,
        nullable=False,
    )
    pipeline_step: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    company: Mapped["Company"] = relationship("Company", back_populates="analyses")
    sources: Mapped[List["Source"]] = relationship(
        "Source", back_populates="analysis"
    )
    findings: Mapped[List["Finding"]] = relationship(
        "Finding", back_populates="analysis"
    )
    llm_results: Mapped[List["LLMResult"]] = relationship(
        "LLMResult", back_populates="analysis"
    )
    report: Mapped[Optional["Report"]] = relationship(
        "Report", back_populates="analysis", uselist=False
    )