"""
GitHub scraper — public API, no token required (60 req/hour unauthenticated).

Searches for the company's GitHub organization.
Used as a traction signal for tech companies: public repos, stars, and
commit activity indicate product development pace and developer engagement.

Relevance filtering: the GitHub org login must have a SequenceMatcher similarity
>= 0.6 with the company name or domain stem to be accepted. This prevents
returning unrelated organizations that share a common word.

API docs: https://docs.github.com/en/rest
"""
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import SourceType, SourceStatus
from app.services.scrapers.base import BaseScraper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://api.github.com/search/users"
_REPOS_URL = "https://api.github.com/orgs/{login}/repos"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
_SIMILARITY_THRESHOLD = 0.6


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def is_relevant(org_login: str, company_name: str, domain: str) -> bool:
    """
    Returns True if the GitHub org login matches the company name or domain.

    For ambiguous (short/single-word) company names, name substring matching
    is disabled — only the full domain stem (e.g. 'iris-eng' from iris-eng.com)
    is used as an exact substring check. This prevents a generic GitHub org
    named 'iris' from matching 'Iris Engineering'.
    For unambiguous multi-word names, both name and domain_stem checks apply.
    """
    login = org_login.lower().strip()
    name = company_name.lower().strip()
    domain_stem = domain.split(".")[0].lower() if domain else ""

    is_ambiguous = len(name.replace(" ", "")) <= 8 or " " not in name

    # Unambiguous names: exact substring + fuzzy against name
    if not is_ambiguous:
        if name and (name in login or login in name):
            return True
        if name and _similarity(login, name) >= _SIMILARITY_THRESHOLD:
            return True

    # Domain stem: one-directional only (stem must be IN login, not the other way)
    # This avoids 'iris' login matching domain_stem 'iris-eng' via login-in-stem.
    if domain_stem and len(domain_stem) >= 4 and domain_stem in login:
        return True

    # Domain stem fuzzy: only for unambiguous names (short domain stems are unreliable)
    if not is_ambiguous and domain_stem and len(domain_stem) >= 4 and _similarity(login, domain_stem) >= _SIMILARITY_THRESHOLD:
        return True

    return False


class GitHubScraper(BaseScraper):
    source_type = SourceType.GITHUB

    async def fetch(
        self,
        query: str,
        analysis_id: str,
        db: AsyncSession,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        domain = kwargs.get("domain", "")
        return await self._fetch_org(query, domain, analysis_id, db)

    async def _fetch_org(
        self,
        company_name: str,
        domain: str,
        analysis_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds,
                headers=_HEADERS,
            ) as client:
                search_resp = await client.get(
                    _SEARCH_URL,
                    params={"q": f"{company_name} type:org", "per_page": 10},
                )
                if search_resp.status_code == 403:
                    logger.warning("GitHub API rate limit reached")
                    await self._save_source(
                        analysis_id, db, _SEARCH_URL, "GitHub",
                        None, SourceStatus.FAILED
                    )
                    return None
                search_resp.raise_for_status()
                search_data = search_resp.json()
        except Exception as e:
            logger.warning(f"GitHub search error for '{company_name}': {e}")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "GitHub", None, SourceStatus.FAILED
            )
            return None

        items = search_data.get("items", [])
        if not items:
            logger.info(f"GitHub: no org found for '{company_name}'")
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "GitHub", None, SourceStatus.PARTIAL
            )
            return {"found": False}

        # Find the first org that passes relevance check
        matched_org = None
        for item in items:
            login = item.get("login", "")
            if is_relevant(login, company_name, domain):
                matched_org = item
                logger.info(
                    f"GitHub: matched org '{login}' for '{company_name}' "
                    f"(similarity: {_similarity(login, company_name):.2f})"
                )
                break
            else:
                logger.info(
                    f"GitHub: discarding org '{login}' — insufficient similarity "
                    f"to '{company_name}' (domain: {domain or 'none'})"
                )

        if matched_org is None:
            logger.info(
                f"GitHub: {len(items)} orgs found but none matched "
                f"'{company_name}' with sufficient similarity — discarding"
            )
            await self._save_source(
                analysis_id, db, _SEARCH_URL, "GitHub", None, SourceStatus.PARTIAL
            )
            return {
                "found": False,
                "discarded_reason": "no_relevance_match",
            }

        login = matched_org.get("login")
        org_url = matched_org.get("html_url")

        repos_data = await self._fetch_repos(login)

        result = {
            "found": True,
            "login": login,
            "org_url": org_url,
            "public_repos": matched_org.get("public_repos"),
            "followers": matched_org.get("followers"),
            "repos": repos_data,
            "stars_total": sum(r.get("stars", 0) for r in repos_data),
            "source": "github",
        }

        await self._save_source(
            analysis_id,
            db,
            org_url,
            f"GitHub: {login}",
            str(result)[:500],
            SourceStatus.OK,
        )
        return result

    async def _fetch_repos(self, login: str) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds,
                headers=_HEADERS,
            ) as client:
                resp = await client.get(
                    _REPOS_URL.format(login=login),
                    params={"per_page": 10, "sort": "pushed", "type": "public"},
                )
                if resp.status_code in (404, 403):
                    return []
                resp.raise_for_status()
                repos = resp.json()
        except Exception as e:
            logger.warning(f"GitHub repos error for '{login}': {e}")
            return []

        return [
            {
                "name": r.get("name"),
                "stars": r.get("stargazers_count", 0),
                "description": (r.get("description") or "")[:200],
                "last_push": r.get("pushed_at"),
                "language": r.get("language"),
            }
            for r in repos
        ]


async def fetch_github(
    company_name: str,
    analysis_id: str,
    db: AsyncSession,
    domain: str = "",
) -> Optional[Dict[str, Any]]:
    scraper = GitHubScraper()
    return await scraper.fetch(company_name, analysis_id, db, domain=domain)
