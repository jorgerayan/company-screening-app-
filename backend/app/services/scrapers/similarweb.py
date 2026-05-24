"""
SimilarWeb scraper — Playwright-based, degrades gracefully.

Attempts to extract publicly visible traffic metrics from SimilarWeb
without login. SimilarWeb actively blocks automated access; this scraper
handles all blocked/unavailable scenarios gracefully and never fails
the pipeline.

Domain is extracted from the company's website URL.
"""
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _extract_domain(website_url: str) -> Optional[str]:
    try:
        parsed = urlparse(website_url)
        domain = parsed.netloc.lower().lstrip("www.")
        return domain if domain else None
    except Exception:
        return None


class SimilarWebScraper(BaseScraper):
    source_type = SourceType.SIMILARWEB

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        website_url: Optional[str] = kwargs.get("website_url")
        domain = _extract_domain(website_url) if website_url else None
        if not domain:
            return {"found": False, "reason": "no_domain"}
        return await self._scrape(domain, analysis_id, db)

    async def _scrape(
        self,
        domain: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        url = f"https://www.similarweb.com/website/{domain}/"
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
            logger.warning(f"SimilarWeb scrape blocked or failed for '{domain}': {e}")
            await self._save_source(
                analysis_id, db, url, f"SimilarWeb: {domain}",
                None, SourceStatus.FAILED
            )
            return {"found": False, "reason": "blocked_or_error"}

        result = self._parse(content, domain)
        status = SourceStatus.OK if result.get("found") else SourceStatus.PARTIAL

        await self._save_source(
            analysis_id, db, url, f"SimilarWeb: {domain}", str(result), status
        )
        return result

    def _parse(self, html: str, domain: str) -> Dict[str, Any]:
        # Extract globally visible stats using regex patterns
        # SimilarWeb renders some data in server-side HTML before JS hydration
        global_rank = self._extract(html, r'"globalRank":\s*\{[^}]*"rank":\s*(\d+)')
        category = self._extract(html, r'"category":\s*"([^"]+)"')
        country = self._extract(html, r'"topCountry":\s*"([^"]+)"')
        monthly_visits = self._extract(
            html, r'"engagements":\s*\{[^}]*"visits":\s*"([^"]+)"'
        )

        if not any([global_rank, category, monthly_visits]):
            return {"found": False, "domain": domain}

        return {
            "found": True,
            "domain": domain,
            "global_rank": global_rank,
            "category": category,
            "top_country": country,
            "monthly_visits_estimate": monthly_visits,
            "source": "similarweb",
        }

    def _extract(self, html: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, html)
        return match.group(1) if match else None


async def fetch_similarweb(
    website_url: str,
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = SimilarWebScraper()
    return await scraper.fetch("", analysis_id, db, website_url=website_url)
