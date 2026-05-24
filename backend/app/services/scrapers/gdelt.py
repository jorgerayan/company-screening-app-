"""
GDELT Doc 2.0 scraper — public API, no API key required.

Searches for recent news articles mentioning the company name.
Used to detect press coverage, events, and external traction signals.

API: https://api.gdeltproject.org/api/v2/doc/doc
Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

Returns up to 20 articles sorted by date descending.
Degrades gracefully: empty result set is valid and clearly reported.
Applies relevance filtering to discard articles unrelated to the target company.
"""
from typing import Optional, Dict, Any, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _is_relevant_gdelt(article: Dict[str, Any], company_name: str) -> bool:
    """
    Lightweight pre-filter: returns True if the article plausibly mentions the
    target company. Intentionally lenient — the normalizer's entity-match scoring
    (_score_article_relevance) is the authoritative filter; this function only
    removes clear noise before the articles leave the scraper.

    Accepts when:
    - Full company name appears in title or article domain.
    - ALL significant words (≥4 chars) of a multi-word name appear in title
      (requires ALL, not ANY, to avoid single-word false positives).
    - Company domain stem appears in the article's own domain
      (article is from a site related to the company).

    Removed (vs. previous version):
    - "any single word in title" path  → too many false positives (e.g. any
      article with "engineering" for "Iris Engineering").
    - SequenceMatcher fuzzy match      → accepts unrelated names that happen
      to be similar in length.
    """
    name_lower = company_name.lower().strip()
    title = (article.get("title") or "").lower()
    art_domain = (article.get("domain") or "").lower()

    # Full name in title or article domain
    if name_lower and name_lower in (title + " " + art_domain):
        return True

    # ALL significant words of multi-word name in title
    name_words = [w for w in name_lower.split() if len(w) >= 4]
    if len(name_words) >= 2 and all(w in title for w in name_words):
        return True

    # Article domain contains company domain stem (e.g. article at "iris-eng.es")
    domain_stem = company_name.lower().replace(" ", "")[:12]  # rough stem fallback
    # Prefer actual domain stem if available via kwargs (not accessible here;
    # normalizer handles this with entity_profile)
    if name_lower and len(name_lower) >= 4 and name_lower in art_domain:
        return True

    return False

_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltScraper(BaseScraper):
    source_type = SourceType.GDELT

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_news(query, analysis_id, db)

    async def _fetch_news(
        self,
        company_name: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        params = {
            "query": f'"{company_name}"',
            "mode": "artlist",
            "maxrecords": "20",
            "format": "json",
            "sort": "datedesc",
        }

        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds
            ) as client:
                response = await client.get(_API_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"GDELT HTTP error {e.response.status_code}")
            await self._save_source(
                analysis_id, db, _API_URL, "GDELT", None, SourceStatus.FAILED
            )
            return None
        except Exception as e:
            logger.warning(f"GDELT error: {e}")
            await self._save_source(
                analysis_id, db, _API_URL, "GDELT", None, SourceStatus.FAILED
            )
            return None

        articles: List[Dict[str, Any]] = data.get("articles", [])

        if not articles:
            logger.info(f"GDELT: no articles found for '{company_name}'")
            await self._save_source(
                analysis_id, db, _API_URL, "GDELT", None, SourceStatus.PARTIAL
            )
            return {"found": False, "articles": [], "article_count": 0}

        parsed = self._parse(articles)

        # Relevance filtering — same pattern as google_news.py
        relevant = [a for a in parsed if _is_relevant_gdelt(a, company_name)]
        discarded = len(parsed) - len(relevant)
        if discarded:
            logger.info(
                f"GDELT: discarded {discarded}/{len(parsed)} irrelevant articles "
                f"for '{company_name}'"
            )

        if not relevant:
            logger.info(f"GDELT: no relevant articles after filtering for '{company_name}'")
            await self._save_source(
                analysis_id, db, _API_URL, "GDELT", None, SourceStatus.PARTIAL
            )
            return {
                "found": False,
                "articles": [],
                "article_count": 0,
                "discarded_count": discarded,
            }

        status = SourceStatus.PARTIAL if len(relevant) < 2 else SourceStatus.OK
        await self._save_source(
            analysis_id,
            db,
            _API_URL,
            f"GDELT: {company_name}",
            str(relevant[:5]),
            status,
        )
        return {
            "found": True,
            "article_count": len(relevant),
            "articles": relevant,
            "discarded_count": discarded,
            "source": "gdelt",
        }

    def _parse(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for a in articles:
            result.append(
                {
                    "title": a.get("title"),
                    "url": a.get("url"),
                    "domain": a.get("domain"),
                    "date": a.get("seendate"),
                    "language": a.get("language"),
                }
            )
        return result


async def fetch_gdelt_news(
    company_name: str,
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = GdeltScraper()
    return await scraper.fetch(company_name, analysis_id, db)
