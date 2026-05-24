"""
Glassdoor scraper — Playwright-based, degrades gracefully.

Attempts to extract publicly visible employer ratings from Glassdoor
without login. Glassdoor aggressively blocks automated access; this
scraper handles all blocked/unavailable scenarios gracefully.

Useful signal for risk analysis: low ratings or declining employee
satisfaction are material risks in M&A screening.
"""
import re
from typing import Optional, Dict, Any
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://www.glassdoor.com/Search/results.htm?keyword={query}"


class GlassdoorScraper(BaseScraper):
    source_type = SourceType.GLASSDOOR

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        return await self._scrape(query, analysis_id, db)

    async def _scrape(
        self,
        company_name: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        url = _SEARCH_URL.format(query=quote_plus(company_name))
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.set_extra_http_headers(
                        {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
                    )
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    content = await page.content()
                finally:
                    await browser.close()
        except Exception as e:
            logger.warning(f"Glassdoor scrape blocked or failed for '{company_name}': {e}")
            await self._save_source(
                analysis_id, db, url, f"Glassdoor: {company_name}",
                None, SourceStatus.FAILED
            )
            return {"found": False, "reason": "blocked_or_error"}

        result = self._parse(content, company_name)
        status = SourceStatus.OK if result.get("found") else SourceStatus.PARTIAL

        await self._save_source(
            analysis_id, db, url, f"Glassdoor: {company_name}", str(result), status
        )
        return result

    def _parse(self, html: str, company_name: str) -> Dict[str, Any]:
        # Attempt to extract JSON-LD or structured data visible without login
        overall_rating = self._extract_float(
            html, r'"overallRating":\s*([\d.]+)'
        )
        review_count = self._extract_int(
            html, r'"numberOfRatings":\s*(\d+)'
        )
        recommend_pct = self._extract_int(
            html, r'"recommendToFriend":\s*([\d.]+)'
        )
        ceo_approval = self._extract_int(
            html, r'"ceoApproval":\s*([\d.]+)'
        )

        if overall_rating is None and review_count is None:
            return {"found": False, "company": company_name}

        return {
            "found": True,
            "company": company_name,
            "overall_rating": overall_rating,
            "review_count": review_count,
            "recommend_pct": recommend_pct,
            "ceo_approval_pct": ceo_approval,
            "source": "glassdoor",
        }

    def _extract_float(self, html: str, pattern: str) -> Optional[float]:
        match = re.search(pattern, html)
        try:
            return float(match.group(1)) if match else None
        except (ValueError, AttributeError):
            return None

    def _extract_int(self, html: str, pattern: str) -> Optional[int]:
        match = re.search(pattern, html)
        try:
            return int(float(match.group(1))) if match else None
        except (ValueError, AttributeError):
            return None


async def fetch_glassdoor(
    company_name: str,
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = GlassdoorScraper()
    return await scraper.fetch(company_name, analysis_id, db)
