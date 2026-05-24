"""
Wikipedia scraper — public REST API, no key required.

Fetches the Wikipedia article summary for the company.
Tries multiple strategies: Spanish first, then English, then name variations.
Used to obtain an authoritative, neutral description of the company.

API docs: https://en.wikipedia.org/api/rest_v1/
"""
import re as _re
from typing import Optional, Dict, Any, List
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
_MEDIAWIKI_API = "https://{lang}.wikipedia.org/w/api.php"

# Wikipedia's API requires a descriptive User-Agent for automated requests.
# Requests without one (or with generic httpx defaults) receive 403 Forbidden.
# https://www.mediawiki.org/wiki/API:Etiquette#The_User-Agent_header
_WIKI_HEADERS = {
    "User-Agent": "CompanyScreeningBot/1.0 (M&A pre-screening pipeline; non-commercial research)",
}

# Infobox fields that name people relevant to M&A management analysis.
_INFOBOX_PEOPLE_FIELDS = (
    "key_people", "founders", "founder", "ceo", "chairman",
    "president", "director_general",
)


def _parse_infobox_people(wikitext: str) -> str:
    """
    Extract named-person fields from raw wikitext (section 0 / lead section).
    Strips wikitext markup and returns a compact "field: value" block,
    or "" if no relevant fields found.
    """
    results = []
    for field in _INFOBOX_PEOPLE_FIELDS:
        m = _re.search(
            rf"^\s*\|\s*{field}\s*=\s*(.+?)(?=^\s*\||\n\s*\}}|\Z)",
            wikitext,
            _re.IGNORECASE | _re.MULTILINE | _re.DOTALL,
        )
        if not m:
            continue
        raw = m.group(1).strip()
        # Expand list templates BEFORE stripping: {{ubl|A|B}} → "A, B"
        raw = _re.sub(
            r"\{\{(?:ubl|hlist|flatlist|plainlist|unbulleted list)\|([^}]+)\}\}",
            lambda x: ", ".join(p.strip() for p in x.group(1).split("|")),
            raw,
            flags=_re.IGNORECASE,
        )
        # Strip remaining wikitext markup
        raw = _re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", raw)  # [[X|Y]] → Y
        raw = _re.sub(r"<ref\b[^/]*/?>.*?</ref>", "", raw, flags=_re.DOTALL)  # <ref>
        raw = _re.sub(r"<ref\b[^>]*/?>", "", raw)                       # self-closing <ref/>
        raw = _re.sub(r"<[^>]+>", " ", raw)                             # other HTML tags
        raw = _re.sub(r"\{\{[^}]*?\}\}", " ", raw)                      # remaining {{templates}}
        raw = _re.sub(r"'{2,}", "", raw)                                 # bold/italic
        raw = _re.sub(r"\s+", " ", raw).strip().strip(",;")
        if len(raw) > 2:
            results.append(f"{field}: {raw}")
    return "\n".join(results)


async def _fetch_infobox_people(title: str, lang: str) -> str:
    """
    Non-blocking secondary call to MediaWiki Action API to retrieve section-0
    wikitext and extract key_people / founders / ceo infobox fields.
    Returns "" on any failure — calling code always falls back to prose extract.
    """
    try:
        async with httpx.AsyncClient(timeout=4.0, headers=_WIKI_HEADERS) as client:
            resp = await client.get(
                _MEDIAWIKI_API.format(lang=lang),
                params={
                    "action": "query",
                    "prop": "revisions",
                    "titles": title,
                    "rvprop": "content",
                    "rvsection": "0",    # lead section only — contains infobox
                    "rvslots": "main",
                    "format": "json",
                    "formatversion": "2",
                },
            )
            resp.raise_for_status()
            pages = resp.json().get("query", {}).get("pages", [])
            if not pages:
                return ""
            revs = pages[0].get("revisions", [])
            if not revs:
                return ""
            wikitext = revs[0].get("slots", {}).get("main", {}).get("content", "")
            return _parse_infobox_people(wikitext)
    except Exception:
        return ""


def _name_variants(company_name: str) -> List[str]:
    """
    Generate name variants to try against Wikipedia.
    Order matters — more specific first.
    """
    name = company_name.strip()
    variants = [name]

    # If name has multiple words, try first two words and first word alone
    words = name.split()
    if len(words) >= 3:
        variants.append(" ".join(words[:2]))
    if len(words) >= 2:
        variants.append(words[0])

    # Deduplicate while preserving order
    seen = set()
    result = []
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower())
            result.append(v)
    return result


class WikipediaScraper(BaseScraper):
    source_type = SourceType.WIKIPEDIA

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_summary(query, analysis_id, db)

    async def _fetch_summary(
        self,
        company_name: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        variants = _name_variants(company_name)

        # Try each variant in Spanish first, then English
        for variant in variants:
            for lang in ("es", "en"):
                result = await self._try_lang(variant, lang, analysis_id, db)
                if result:
                    return result

        # Nothing found
        await self._save_source(
            analysis_id, db, None, "Wikipedia", None, SourceStatus.PARTIAL
        )
        return {"found": False}

    async def _try_lang(
        self,
        company_name: str,
        lang: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        title = quote(company_name)
        url = _SUMMARY_URL.format(lang=lang, title=title)
        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds,
                headers=_WIKI_HEADERS,
            ) as client:
                response = await client.get(url)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError:
            return None
        except Exception as e:
            logger.warning(f"Wikipedia ({lang}) error for '{company_name}': {e}")
            return None

        if data.get("type") == "disambiguation":
            return None

        extract = data.get("extract", "")
        if not extract or len(extract) < 50:
            return None

        wiki_url = (
            data.get("content_urls", {}).get("desktop", {}).get("page")
            or data.get("canonicalurl")
        )

        await self._save_source(
            analysis_id,
            db,
            wiki_url,
            f"Wikipedia ({lang.upper()}): {data.get('title', company_name)}",
            extract[:500],
            SourceStatus.OK,
        )

        # Augment with infobox key_people / founders — the REST summary API
        # only returns prose text; structured infobox data requires a separate
        # MediaWiki API call.  Non-blocking: on any failure we fall back to the
        # prose extract alone.
        #
        # Non-English Wikipedia articles often have minimal infoboxes (e.g. the
        # Spanish Glovo article has only a logo, no founders field).  When the
        # primary-language infobox returns nothing, try the English Wikipedia
        # infobox as a fallback — it is usually the most complete.
        page_title = data.get("title") or company_name
        infobox_people = await _fetch_infobox_people(page_title, lang)
        if not infobox_people and lang != "en":
            infobox_people = await _fetch_infobox_people(page_title, "en")
            if infobox_people:
                logger.info(
                    "Wikipedia infobox: primary lang=%s had no people data — "
                    "English fallback succeeded for title=%r",
                    lang, page_title,
                )
        logger.info(
            "Wikipedia infobox fetch: title=%r lang=%s found=%r",
            page_title, lang, infobox_people or "(none)",
        )

        if infobox_people:
            # Prepend infobox block so the LLM sees structured executive data
            # immediately, before the prose.  Total size stays within ~3 000 chars.
            summary_text = (
                f"[Wikipedia infobox — key people]\n{infobox_people}\n\n"
                f"[Wikipedia article text]\n{extract[:2600]}"
            )
        else:
            summary_text = extract[:3000]

        return {
            "found": True,
            "title": page_title,
            "summary": summary_text,
            # key_people is stored as a separate structured field so downstream
            # injection code can use it directly without re-parsing the summary.
            "key_people": infobox_people,   # "" when infobox fetch failed/empty
            "url": wiki_url,
            "language": lang,
            "source": "wikipedia",
        }


async def fetch_wikipedia(
    company_name: str,
    analysis_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    scraper = WikipediaScraper()
    return await scraper.fetch(company_name, analysis_id, db)
