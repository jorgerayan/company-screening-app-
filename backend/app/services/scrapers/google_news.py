"""
Google News RSS scraper — no API key required.

Fetches recent news articles mentioning the company from Google News RSS feed.
Supplements GDELT with broader, more current coverage.
Degrades gracefully on any error.

Relevance filtering: stricter for generic single-word names, relaxed for
multi-word or clearly unique names.
"""
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://news.google.com/rss/search"
_MAX_ARTICLES = 10

# Single-word names that are too generic to trust without domain confirmation
_GENERIC_SINGLE_WORDS = {
    "base", "alpha", "nova", "prime", "core", "apex", "arc", "edge",
    "hub", "lab", "labs", "tech", "data", "cloud", "net", "pro",
    "plus", "one", "zero", "next", "link", "node", "flux",
}


def _extract_domain(website_url: str) -> str:
    """Extract bare domain from a URL, e.g. 'https://base10.es' → 'base10.es'."""
    domain = website_url.lower()
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    return domain.split("/")[0].strip()


def _is_generic_name(company_name: str) -> bool:
    """Returns True if the name is a single generic word that needs stricter filtering."""
    words = company_name.lower().strip().split()
    return len(words) == 1 and words[0] in _GENERIC_SINGLE_WORDS


def is_relevant(article: Dict[str, Any], company_name: str, domain: str) -> bool:
    """
    Lightweight pre-filter for Google News RSS results. Intentionally lenient —
    the normalizer's entity-match scoring is the authoritative filter; this
    function only removes obvious noise before results leave the scraper.

    Accepts when:
    - Full company name appears in title (not source_name — avoids "Iris Magazine"
      passing because "iris" appears in the publication name, not the article).
    - ALL significant words (≥5 chars) of a multi-word name appear in title+source.
    - Company domain or domain stem appears in title or source_name.

    Removed (vs. previous version):
    - "last resort: any single word (≥4 chars) in title" path — caused false
      positives for any article mentioning a word that is also part of the
      company name (e.g. "engineering" for "Iris Engineering").
    """
    name_lower = company_name.lower().strip()
    domain_stem = domain.split(".")[0].lower() if domain else ""

    title = (article.get("title") or "").lower()
    source_name = (article.get("source_name") or "").lower()
    text = title + " " + source_name

    # Full name in title only (not source_name) — guards against the publication
    # name containing the company name (e.g. "Iris Magazine" matching "IRIS").
    if not _is_generic_name(company_name):
        if name_lower and name_lower in title:
            return True
        # ALL significant words of a multi-word name in title+source_name
        words = [w for w in name_lower.split() if len(w) >= 5]
        if len(words) >= 2 and all(w in text for w in words):
            return True

    # Domain / domain-stem in title or source_name
    if domain_stem and len(domain_stem) >= 4 and domain_stem in text:
        return True
    if domain and domain in text:
        return True

    return False


class GoogleNewsScraper(BaseScraper):
    source_type = SourceType.GOOGLE_NEWS

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        domain = kwargs.get("domain", "")
        return await self._fetch_rss(query, domain, analysis_id, db)

    async def _fetch_rss(
        self,
        company_name: str,
        domain: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        # Use quoted company name for precision; add domain only for generic names
        if _is_generic_name(company_name) and domain:
            query_str = f'"{company_name}" {domain}'
        else:
            query_str = f'"{company_name}"'

        url = f"{_BASE_URL}?q={quote_plus(query_str)}&hl=es&gl=ES&ceid=ES:es"

        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; screening-bot/1.0)"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                rss_text = response.text
        except Exception as e:
            logger.warning(f"Google News RSS error for '{company_name}': {e}")
            await self._save_source(
                analysis_id, db, url, "Google News", None, SourceStatus.FAILED
            )
            return None

        raw_articles = self._parse_rss(rss_text)

        relevant = [a for a in raw_articles if is_relevant(a, company_name, domain)]
        discarded = len(raw_articles) - len(relevant)
        if discarded:
            logger.info(
                f"Google News: discarded {discarded}/{len(raw_articles)} irrelevant "
                f"articles for '{company_name}'"
            )

        if not relevant:
            logger.info(f"Google News: no relevant articles for '{company_name}'")
            await self._save_source(
                analysis_id, db, url, "Google News", None, SourceStatus.PARTIAL
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
            url,
            f"Google News: {company_name}",
            str(relevant[:3]),
            status,
        )
        return {
            "found": True,
            "articles": relevant[:_MAX_ARTICLES],
            "article_count": len(relevant),
            "discarded_count": discarded,
            "source": "google_news",
        }

    def _parse_rss(self, rss_text: str) -> List[Dict[str, Any]]:
        articles = []
        try:
            root = ET.fromstring(rss_text)
            channel = root.find("channel")
            if channel is None:
                return []
            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                pub_date_el = item.find("pubDate")
                source_el = item.find("source")
                articles.append(
                    {
                        "title": title_el.text if title_el is not None else None,
                        "url": link_el.text if link_el is not None else None,
                        "date": pub_date_el.text if pub_date_el is not None else None,
                        "source_name": (
                            source_el.text if source_el is not None else None
                        ),
                    }
                )
        except ET.ParseError as e:
            logger.warning(f"Google News XML parse error: {e}")
        return articles


async def fetch_google_news(
    company_name: str,
    analysis_id: str,
    db: AsyncSession,
    domain: str = "",
) -> Optional[Dict[str, Any]]:
    scraper = GoogleNewsScraper()
    return await scraper.fetch(company_name, analysis_id, db, domain=domain)
