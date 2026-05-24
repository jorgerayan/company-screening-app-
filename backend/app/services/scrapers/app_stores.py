"""
App Store scraper — iTunes Search API (public, no key required).

Searches for a mobile app associated with the company on the Apple App Store.
Used as a traction signal: rating, review count, and last-update date indicate
product quality and activity level.

Relevance filtering: the app name or developer must match the company name or
domain. This prevents returning unrelated apps that happen to match a generic
search term.

iTunes API docs: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
"""
from typing import Optional, Dict, Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ITUNES_URL = "https://itunes.apple.com/search"


def is_relevant(app: Dict[str, Any], company_name: str, domain: str) -> bool:
    """
    Returns True if the app is plausibly the target company's product.
    Checks app name and developer name against company name and domain stem.
    For short/single-word names, the developer must also contain a match to
    avoid accepting homonym apps (e.g. a transit app named 'Iris' by RideCo
    when the target company is 'Iris Engineering').
    """
    name_lower = company_name.lower().strip()
    domain_stem = domain.split(".")[0].lower() if domain else ""

    app_name = (app.get("trackName") or "").lower()
    developer = (app.get("artistName") or "").lower()
    combined = f"{app_name} {developer}"

    is_short = len(name_lower.replace(" ", "")) <= 8 or " " not in name_lower

    # Direct company name match — for short names require developer to also match
    if name_lower and name_lower in combined:
        if not is_short:
            return True
        # Short names: app_name match alone is insufficient (homonym risk); developer must match
        if name_lower in developer or (domain_stem and len(domain_stem) >= 4 and domain_stem in developer):
            return True
    # Domain stem match (e.g. 'factorial' from 'factorialhr.com') — always reliable
    if domain_stem and len(domain_stem) >= 4 and domain_stem in combined:
        return True
    # Multi-word company name: all significant words in combined
    words = [w for w in name_lower.split() if len(w) >= 4]
    if words and len(words) >= 2 and all(w in combined for w in words):
        return True
    return False


class AppStoresScraper(BaseScraper):
    source_type = SourceType.APP_STORES

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        domain = kwargs.get("domain", "")
        return await self._search_app_store(query, domain, analysis_id, db)

    async def _search_app_store(
        self,
        company_name: str,
        domain: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        params = {
            "term": company_name,
            "entity": "software",
            "limit": 10,
            "country": "us",
        }
        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds
            ) as client:
                response = await client.get(_ITUNES_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"App Store error for '{company_name}': {e}")
            await self._save_source(
                analysis_id, db, _ITUNES_URL, "App Store", None, SourceStatus.FAILED
            )
            return None

        results = data.get("results", [])
        if not results:
            logger.info(f"App Store: no apps found for '{company_name}'")
            await self._save_source(
                analysis_id, db, _ITUNES_URL, "App Store", None, SourceStatus.PARTIAL
            )
            return {"found": False, "app_store": None}

        # Find first result that passes relevance check
        matched_app = None
        for app in results:
            if is_relevant(app, company_name, domain):
                matched_app = app
                break

        if matched_app is None:
            logger.info(
                f"App Store: {len(results)} apps found but none matched "
                f"'{company_name}' (domain: {domain or 'none'}) — discarding"
            )
            await self._save_source(
                analysis_id, db, _ITUNES_URL, "App Store", None, SourceStatus.PARTIAL
            )
            return {
                "found": False,
                "app_store": None,
                "discarded_reason": "no_relevance_match",
            }

        extracted = {
            "name": matched_app.get("trackName"),
            "developer": matched_app.get("artistName"),
            "rating": matched_app.get("averageUserRating"),
            "rating_count": matched_app.get("userRatingCount"),
            "description": (matched_app.get("description") or "")[:500],
            "last_updated": matched_app.get("currentVersionReleaseDate"),
            "url": matched_app.get("trackViewUrl"),
            "genres": matched_app.get("genres", []),
        }

        # "confirmed" = domain_stem (compound, e.g. "iris-eng") appears in developer name.
        # A plain name match (e.g. developer="Iris AI Inc" for company="Iris") is ambiguous
        # when there are multiple companies with the same short name.
        developer_lower = (matched_app.get("artistName") or "").lower()
        domain_stem = domain.split(".")[0].lower() if domain else ""
        confirmed = bool(
            domain_stem and len(domain_stem) >= 4 and domain_stem in developer_lower
        )

        await self._save_source(
            analysis_id,
            db,
            extracted["url"],
            f"App Store: {extracted['name']}",
            str(extracted),
            SourceStatus.OK,
        )
        return {
            "found": True,
            "confirmed": confirmed,
            "app_store": extracted,
            "source": "app_stores",
        }


async def fetch_app_stores(
    company_name: str,
    analysis_id: str,
    db: AsyncSession,
    domain: str = "",
) -> Optional[Dict[str, Any]]:
    scraper = AppStoresScraper()
    return await scraper.fetch(company_name, analysis_id, db, domain=domain)
