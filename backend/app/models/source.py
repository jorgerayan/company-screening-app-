import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.database import Base


class SourceType(str, enum.Enum):
    WEBSITE = "website"
    OPENCORPORATES = "opencorporates"
    BORME = "borme"
    GDELT = "gdelt"
    CROSSREF = "crossref"
    GOOGLE_NEWS = "google_news"
    WIKIPEDIA = "wikipedia"
    APP_STORES = "app_stores"
    GITHUB = "github"
    SIMILARWEB = "similarweb"
    GLASSDOOR = "glassdoor"
    OTHER = "other"


class SourceStatus(str, enum.Enum):
    OK = "ok"
    FAILED = "failed"
    PARTIAL = "partial"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False
    )
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[SourceStatus] = mapped_column(
        SAEnum(SourceStatus, values_callable=lambda x: [e.value for e in x]),
        default=SourceStatus.OK,
    )
    raw_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped["Analysis"] = relationship("Analysis", back_populates="sources")
    findings: Mapped[List["Finding"]] = relationship(
        "Finding", back_populates="source"
    )