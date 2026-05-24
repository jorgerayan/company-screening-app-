"""
Base scraper contract.
All scrapers implement fetch() and use _save_source() to persist trazabilidad.
On any failure, scrapers return None — the orchestrator continues gracefully.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source, SourceType, SourceStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Hard cap on raw content stored per source (avoids bloating the DB)
MAX_RAW_CONTENT_CHARS = 50_000


class BaseScraper(ABC):
    source_type: SourceType

    @abstractmethod
    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch data for the given query.
        Returns a normalized dict on success, None on failure.
        Must never raise — catch all exceptions internally.
        """
        ...

    async def _save_source(
        self,
        analysis_id: str,
        db: AsyncSession,
        url: Optional[str],
        title: Optional[str],
        raw_content: Optional[str],
        status: SourceStatus = SourceStatus.OK,
    ) -> Source:
        """Persist a Source record for trazabilidad."""
        source = Source(
            analysis_id=analysis_id,
            source_type=self.source_type,
            url=url,
            title=title,
            raw_content=(
                raw_content[:MAX_RAW_CONTENT_CHARS] if raw_content else None
            ),
            status=status,
        )
        db.add(source)
        await db.flush()
        return source
