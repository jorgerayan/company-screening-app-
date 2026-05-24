"""
OpenCorporates scraper — free public API, no API key required.

Returns basic company registration data: legal name, company number,
jurisdiction, type, status, incorporation date, registered address.
Used as the primary source of verified corporate facts.

Free tier: ~500 req/day. No auth needed for search.
API docs: https://api.opencorporates.com/
"""
from typing import Optional, Dict, Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://api.opencorporates.com/v0.4/companies/search"

# Map user-provided country strings to OpenCorporates jurisdiction codes
_JURISDICTION_MAP: Dict[str, str] = {
    "es": "es",
    "spain": "es",
    "españa": "es",
    "uk": "gb",
    "united kingdom": "gb",
    "gb": "gb",
    "us": "us_de",
    "united states": "us_de",
    "usa": "us_de",
    "de": "de",
    "germany": "de",
    "alemania": "de",
    "fr": "fr",
    "france": "fr",
    "francia": "fr",
    "pt": "pt",
    "portugal": "pt",
    "mx": "mx",
    "mexico": "mx",
    "méjico": "mx",
}


class OpenCorporatesScraper(BaseScraper):
    source_type = SourceType.OPENCORPORATES

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        country: Optional[str] = kwargs.get("country")
        return await self._search(query, country, analysis_id, db)

    async def _search(
        self,
        company_name: str,
        country: Optional[str],
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "q": company_name,
            "per_page": 5,
            "format": "json",
        }
        if country:
            jurisdiction = _JURISDICTION_MAP.get(country.lower().strip())
            if jurisdiction:
                params["jurisdiction_code"] = jurisdiction

        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds
            ) as client:
                response = await client.get(_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"OpenCorporates HTTP error {e.response.status_code}")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "OpenCorporates",
                None, SourceStatus.FAILED
            )
            return None
        except Exception as e:
            logger.warning(f"OpenCorporates error: {e}")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "OpenCorporates",
                None, SourceStatus.FAILED
            )
            return None

        companies = data.get("results", {}).get("companies", [])
        if not companies:
            logger.info(f"OpenCorporates: no results for '{company_name}'")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "OpenCorporates",
                None, SourceStatus.PARTIAL
            )
            return {"found": False, "results": []}

        # Take best match (first result)
        best = companies[0].get("company", {})
        result = self._extract(best)

        await self._save_source(
            analysis_id,
            db,
            best.get("opencorporates_url"),
            best.get("name"),
            str(result),
            SourceStatus.OK,
        )
        return result

    def _extract(self, company: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "found": True,
            "legal_name": company.get("name"),
            "company_number": company.get("company_number"),
            "jurisdiction": company.get("jurisdiction_code"),
            "company_type": company.get("company_type"),
            "status": company.get("current_status"),
            "incorporation_date": company.get("incorporation_date"),
            "dissolution_date": company.get("dissolution_date"),
            "registered_address": self._fmt_address(
                company.get("registered_address")
            ),
            "opencorporates_url": company.get("opencorporates_url"),
            "source": "opencorporates",
        }

    def _fmt_address(self, addr: Optional[Dict[str, Any]]) -> Optional[str]:
        if not addr:
            return None
        parts = [
            addr.get("street_address"),
            addr.get("locality"),
            addr.get("region"),
            addr.get("postal_code"),
            addr.get("country"),
        ]
        return ", ".join(p for p in parts if p)


async def fetch_opencorporates(
    company_name: str,
    country: Optional[str],
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = OpenCorporatesScraper()
    return await scraper.fetch(company_name, analysis_id, db, country=country)
