"""
BORME scraper — Boletín Oficial del Registro Mercantil (Spain).

Only activated for Spanish companies (country == "es" / "spain").
Uses the BOE public search interface via HTTP (no API key needed).
Extracts registry entries: constitutions, director changes, capital changes, etc.

Degrades gracefully: skipped entirely for non-Spanish companies,
returns partial result if BOE search is unavailable.
"""
import re
from typing import Optional, Dict, Any, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://www.boe.es/buscar/borme.php"
_SPANISH_COUNTRIES = {"es", "spain", "españa", "espana"}


class BormeScraper(BaseScraper):
    source_type = SourceType.BORME

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        country: Optional[str] = kwargs.get("country")
        if country and country.lower().strip() not in _SPANISH_COUNTRIES:
            logger.debug("Skipping BORME: company not Spanish")
            return None
        return await self._search(query, analysis_id, db)

    async def _search(
        self,
        company_name: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        params = {
            "campo[0]": "ANUNCIO",
            "dato[0]": company_name,
            "campo[1]": "NIF",
            "dato[1]": "",
            "campo[2]": "TIPO",
            "dato[2]": "",
            "campo[3]": "ACTO",
            "dato[3]": "",
            "campo[4]": "PROVINCIA",
            "dato[4]": "",
            "campo[5]": "FECHA_INICIO",
            "dato[5]": "",
            "campo[6]": "FECHA_FIN",
            "dato[6]": "",
            "sort_field[0]": "DOC",
            "sort_order[0]": "desc",
            "accion": "Buscar",
        }

        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds,
                headers={"Accept-Language": "es-ES,es;q=0.9"},
                follow_redirects=True,
            ) as client:
                response = await client.get(_SEARCH_URL, params=params)
                response.raise_for_status()
                html = response.text
        except httpx.HTTPStatusError as e:
            logger.warning(f"BORME HTTP error {e.response.status_code}")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "BORME", None, SourceStatus.FAILED
            )
            return None
        except Exception as e:
            logger.warning(f"BORME error: {e}")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "BORME", None, SourceStatus.FAILED
            )
            return None

        entries = self._parse(html)

        if not entries:
            logger.info(f"BORME: no entries for '{company_name}'")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "BORME", None, SourceStatus.PARTIAL
            )
            return {"found": False, "entries": []}

        await self._save_source(
            analysis_id,
            db,
            _SEARCH_URL,
            f"BORME: {company_name}",
            str(entries[:5]),
            SourceStatus.OK,
        )
        return {
            "found": True,
            "entry_count": len(entries),
            "entries": entries[:10],
            "source": "borme",
        }

    def _parse(self, html: str) -> List[Dict[str, str]]:
        """
        Extract BORME entries from the BOE search results HTML.
        Targets anchor tags inside result list items.
        """
        entries: List[Dict[str, str]] = []

        # Match links to BORME documents within result <li> elements
        pattern = re.compile(
            r'<a[^>]+href="(/diario_borme/[^"]+)"[^>]*>(.*?)</a>'
            r'.*?(\d{2}/\d{2}/\d{4})',
            re.IGNORECASE | re.DOTALL,
        )
        for m in pattern.finditer(html):
            href = m.group(1).strip()
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            date = m.group(3)
            if href and title:
                url = f"https://www.boe.es{href}"
                entries.append({"title": title, "url": url, "date": date})

        return entries


async def fetch_borme(
    company_name: str,
    country: Optional[str],
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = BormeScraper()
    return await scraper.fetch(company_name, analysis_id, db, country=country)
