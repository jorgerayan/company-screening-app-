"""
Website scraper — Playwright (headless Chromium).

Scrapes up to `max_website_pages` pages from the company website, targeting
paths that typically contain product/company information. Saves a Source record
per page for trazabilidad. Returns combined extracted text for LLM consumption.

Design decisions:
- Runs in async mode to avoid blocking FastAPI's event loop.
- Uses domcontentloaded (not networkidle) to stay within timeouts.
- Strips nav/footer/scripts before extracting text to reduce noise.
- Sleeps 500ms between pages to avoid rate-limiting.
"""
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Pages to attempt, in priority order (home is always the seed URL).
# Leadership/governance paths are placed early because management.py relies
# on them and they are the highest-value pages for executive identification.
_TARGET_PATH_HINTS: List[str] = [
    # Identity / about
    "/about", "/about-us", "/quienes-somos", "/nosotros",
    # Leadership — English variants
    "/team", "/our-team", "/leadership", "/leadership-team",
    "/management", "/management-team", "/board", "/board-of-directors",
    "/governance", "/corporate-governance", "/officers", "/executive-team",
    "/investor-relations", "/investors", "/ir",
    # Leadership — Spanish variants
    "/equipo", "/nuestro-equipo", "/liderazgo", "/consejo",
    "/consejo-de-administracion", "/directivos", "/direccion",
    "/organos-de-gobierno", "/gobierno-corporativo",
    # Product / pricing
    "/pricing", "/precios", "/planes",
    "/product", "/products", "/producto", "/soluciones", "/solutions",
    # Social proof / customers
    "/customers", "/clients", "/casos-de-exito", "/case-studies",
    # Content / jobs
    "/blog",
    "/careers", "/jobs", "/trabaja-con-nosotros",
]

# Per-page text cap sent to the normalizer (keeps token costs reasonable)
_MAX_PAGE_TEXT_CHARS = 3_000

# Keywords used to discover leadership/governance/investor links on the homepage
# (covers companies whose URL structure does not match _TARGET_PATH_HINTS, e.g.
# Inditex's /itxcomweb/es/grupo/gobierno-corporativo).
# Match against href and link text, case-insensitive.
_LINK_DISCOVERY_KEYWORDS: List[str] = [
    # English
    "governance", "board", "leadership", "investor", "investors",
    "management", "officers", "directors", "executives",
    "annual-report", "annual_report", "annualreport", "shareholders",
    # Spanish
    "gobierno", "consejo", "consejeros", "directiv", "lideraz",
    "inversor", "inversores", "accionist", "junta", "memoria-anual",
    "informe-anual", "equipo",
]
# Cap on discovered links to keep the candidate list manageable
_MAX_DISCOVERED_LINKS = 12


def _clean_text(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return "\n".join(lines)


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class WebsiteScraper(BaseScraper):
    source_type = SourceType.WEBSITE

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        website_url: str = kwargs.get("website_url", query)
        return await self._scrape(website_url, analysis_id, db)

    async def _scrape(
        self,
        start_url: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: playwright install chromium")
            return None

        base = _base_url(start_url)
        candidate_urls: List[str] = [start_url] + [
            urljoin(base, path) for path in _TARGET_PATH_HINTS
        ]

        pages_data: List[Dict[str, str]] = []
        visited: set = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (compatible; CompanyScreeningBot/1.0; "
                    "analysis-only)"
                ),
                java_script_enabled=True,
            )

            # Process homepage first (always candidate_urls[0]) to discover real
            # leadership/governance/investor links that may not match the static hints.
            visited.add(start_url)
            home_result = await self._scrape_page(ctx, start_url, analysis_id, db)
            if home_result:
                pages_data.append(home_result)
                discovered = await self._discover_links_from_homepage(
                    ctx, start_url, base
                )
                if discovered:
                    logger.info(
                        "[website_scraper] Discovered %d relevant links from homepage of %s",
                        len(discovered), start_url,
                    )
                    # Prepend discovered links so they take priority over guessed ones.
                    candidate_urls = [start_url] + discovered + [
                        u for u in candidate_urls[1:] if u not in discovered
                    ]
            await asyncio.sleep(0.5)

            for url in candidate_urls[1:]:
                if len(pages_data) >= settings.max_website_pages:
                    break
                if url in visited:
                    continue
                visited.add(url)

                page_result = await self._scrape_page(ctx, url, analysis_id, db)
                if page_result:
                    pages_data.append(page_result)
                await asyncio.sleep(0.5)

            await browser.close()

        if not pages_data:
            logger.warning(f"No content extracted from {start_url}")
            return None

        combined = "\n\n---\n\n".join(
            f"[{p['url']}]\n{p['text']}" for p in pages_data
        )
        return {
            "base_url": start_url,
            "pages_scraped": len(pages_data),
            "pages": pages_data,
            "combined_text": combined,
        }

    async def _discover_links_from_homepage(
        self,
        ctx: Any,
        homepage_url: str,
        base: str,
    ) -> List[str]:
        """
        Re-open the homepage briefly and extract internal anchor URLs whose
        href OR link text matches any keyword in _LINK_DISCOVERY_KEYWORDS.

        Helps for companies whose governance / investor / leadership pages
        live at non-standard paths (e.g. Inditex's /itxcomweb/es/grupo/...).

        Returns a deduplicated list of absolute URLs on the same host as base,
        capped at _MAX_DISCOVERED_LINKS.
        """
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        from urllib.parse import urlparse

        host = urlparse(base).netloc.lower()
        page = await ctx.new_page()
        try:
            response = await page.goto(
                homepage_url,
                timeout=settings.scrape_timeout_seconds * 1000,
                wait_until="domcontentloaded",
            )
            if not response or response.status >= 400:
                await page.close()
                return []

            anchors = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: (a.innerText || a.textContent || '').trim().slice(0, 100)
                }))"""
            )
            await page.close()
        except PlaywrightTimeout:
            await page.close()
            return []
        except Exception as e:
            logger.debug(f"Link discovery failed for {homepage_url}: {e}")
            await page.close()
            return []

        discovered: List[str] = []
        seen: set = set()
        for a in anchors or []:
            href = (a.get("href") or "").strip()
            text = (a.get("text") or "").strip().lower()
            if not href:
                continue
            try:
                parsed = urlparse(href)
            except Exception:
                continue
            # Same host only — never follow off-domain links from homepage discovery.
            if parsed.netloc and parsed.netloc.lower() != host:
                continue
            href_lower = href.lower()
            # Match either in the URL path or the visible link text.
            target = f"{parsed.path.lower()} {text}"
            if not any(kw in target for kw in _LINK_DISCOVERY_KEYWORDS):
                continue
            # Strip fragments to avoid duplicate hits to the same page.
            clean = href.split("#", 1)[0]
            if clean in seen or clean == homepage_url:
                continue
            seen.add(clean)
            discovered.append(clean)
            if len(discovered) >= _MAX_DISCOVERED_LINKS:
                break
        return discovered

    async def _scrape_page(
        self,
        ctx: Any,
        url: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, str]]:
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        page = await ctx.new_page()
        try:
            response = await page.goto(
                url,
                timeout=settings.scrape_timeout_seconds * 1000,
                wait_until="domcontentloaded",
            )
            if not response or response.status >= 400:
                await page.close()
                await self._save_source(
                    analysis_id, db, url, None, None, SourceStatus.FAILED
                )
                return None

            title = await page.title()

            # Strip non-content elements before extracting text
            raw_text = await page.evaluate(
                """() => {
                    document.querySelectorAll(
                        'nav, footer, script, style, noscript, svg, header'
                    ).forEach(el => el.remove());
                    return document.body ? document.body.innerText : '';
                }"""
            )
            text = _clean_text(raw_text)

            if len(text) < 80:
                # Page has no meaningful content (e.g. redirect placeholder)
                await page.close()
                return None

            await self._save_source(
                analysis_id, db, url, title, text[:10_000], SourceStatus.OK
            )
            await page.close()
            return {"url": url, "title": title, "text": text[:_MAX_PAGE_TEXT_CHARS]}

        except PlaywrightTimeout:
            logger.debug(f"Timeout scraping {url}")
            await page.close()
            await self._save_source(
                analysis_id, db, url, None, None, SourceStatus.FAILED
            )
            return None
        except Exception as e:
            logger.warning(f"Error scraping {url}: {e}")
            await page.close()
            try:
                await self._save_source(
                    analysis_id, db, url, None, None, SourceStatus.FAILED
                )
            except Exception:
                pass
            return None


async def scrape_website(
    website_url: str,
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = WebsiteScraper()
    return await scraper.fetch(
        website_url, analysis_id, db, website_url=website_url
    )
