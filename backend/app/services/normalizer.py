"""
Normalizer — consolidates raw scraper outputs into a single clean dict
ready for LLM module consumption.

Responsibilities:
- Merge data from all scrapers (website, OpenCorporates, GDELT, BORME,
  Google News, Wikipedia, App Stores, GitHub, SimilarWeb, Glassdoor).
- Truncate text to avoid LLM token overload.
- Build the references list for the final report.
- Tag every data item with its source for trazabilidad.
- Track discarded/irrelevant sources in data_quality_warnings.
- Never invent or infer data — only pass through what scrapers returned.
"""
import re
from collections import Counter
from typing import Optional, Dict, Any, List

# Max chars of website text forwarded to LLM modules
_MAX_WEBSITE_TEXT = 15_000
# Max news items forwarded per source
_MAX_NEWS_ITEMS = 10

# Words that carry no discriminating power for company identification.
# Split into English and Spanish for readability; purely structural approach,
# no NLP library required.
_STOPWORDS: frozenset = frozenset({
    # English — common ≥5-char words that appear on every website
    "about", "above", "after", "again", "along", "among", "apply", "being",
    "below", "bring", "build", "built", "click", "comes", "could", "doing",
    "eight", "every", "first", "found", "given", "going", "great", "group",
    "hands", "having", "helps", "hours", "learn", "legal", "light", "limit",
    "links", "makes", "might", "needs", "never", "night", "offer", "often",
    "order", "other", "place", "point", "press", "quite", "range", "reach",
    "ready", "right", "round", "seven", "shall", "short", "since", "small",
    "still", "store", "takes", "their", "there", "these", "those", "three",
    "through", "times", "today", "under", "until", "using", "where", "which",
    "while", "whole", "whose", "would", "years",
    # Spanish — common ≥5-char words, no accents (stripped by tokeniser)
    "entre", "desde", "donde", "forma", "grande", "grupo", "hacia", "hasta",
    "lugar", "mayor", "mejor", "mismo", "mundo", "nunca", "nueva", "nuevo",
    "parte", "puede", "pueden", "quien", "quienes", "segun", "siempre",
    "sobre", "tanto", "tiene", "tienen", "todas", "todos", "traves", "valor",
    # Generic business / web terms — appear everywhere, add no specificity
    "company", "companies", "business", "service", "services", "solution",
    "solutions", "product", "products", "platform", "client", "clients",
    "customer", "customers", "market", "global", "digital", "online",
    "contact", "email", "phone", "address", "working", "project", "projects",
    "management", "enterprise", "industry", "information", "privacy",
    "policy", "terms", "cookie", "cookies", "rights", "reserved", "follow",
    "social", "media", "linkedin", "twitter", "facebook", "instagram",
    # Spanish equivalents
    "empresa", "empresas", "solucion", "soluciones", "servicio", "servicios",
    "producto", "productos", "proyecto", "proyectos", "mercado", "clientes",
    "innovacion", "tecnologia", "sistemas", "modelo", "equipo", "nuestro",
    "nuestros", "nuestra", "nuestras",
})


def _name_words(company_name: str) -> List[str]:
    """Significant words (≥4 chars) from company name, lowercased."""
    return [w for w in company_name.lower().split() if len(w) >= 4]


# Terms whose presence in an article title is strong evidence the article is about
# a *different type of entity* than a company.
# Rules for adding a term here:
#   1. The term must almost never appear in a company's own business vocabulary.
#   2. Its presence must reliably indicate the article is about a non-company entity.
#   3. If a company legitimately uses this term (e.g. a magazine publisher has
#      "magazine" on its website), the fingerprint will contain it and the term
#      will be removed from the unresolved_conflict set automatically.
_ENTITY_CONFLICT_TERMS: frozenset = frozenset({
    # Publications / media
    "magazine", "revista", "fanzine",
    # Cinema / TV — articles about films, not companies
    "film", "pelicula", "biopic",
    # Military hardware
    "missile", "misil", "torpedo", "projectile",
    # Anatomy / biology
    "muscle", "musculo", "anatomical",
    "genus", "species", "especie", "cultivar", "botanical",
    # Astronomy
    "asteroid", "asteroide", "nebula", "constellation",
    # Death notices — never about a company
    "obituary", "obituario", "necrologica",
})


def _build_entity_profile(
    website_text: str,
    company_name: str,
    company_domain: str,
) -> Dict[str, Any]:
    """
    Build a structured identity profile for the target company from reliable signals.

    The profile is the identity anchor used by _score_article_relevance to distinguish
    between "name appears in article" (string co-occurrence) and "article is about this
    entity" (entity identity match).

    Fields returned:
      name_lower        — lowercased company name
      name_words        — significant words (≥4 chars) from the name
      domain            — full domain e.g. "iris-eng.com"
      domain_stem       — first label e.g. "iris-eng"
      domain_parts      — tokenized domain-stem parts e.g. ["iris", "eng"]
      keyword_fingerprint — frozenset of distinctive vocabulary from website text
                            (sector, product, geography, technology, client names)
      has_rich_profile  — True when website content produced ≥10 distinctive words;
                          used to decide whether vocabulary absence is informative
    """
    name_lower = company_name.lower().strip()
    name_words = [w for w in name_lower.split() if len(w) >= 4]

    domain = company_domain.lower().strip() if company_domain else ""
    domain_stem = domain.split(".")[0] if domain else ""
    domain_parts = [p for p in re.split(r"[^a-z]+", domain_stem) if len(p) >= 3]

    # Seed: name components + domain parts (always present, even without website)
    seeds: set = set()
    for w in re.split(r"[^a-z]+", name_lower):
        if len(w) >= 3:
            seeds.add(w)
    for p in domain_parts:
        seeds.add(p)

    keyword_fingerprint: frozenset = frozenset(seeds)
    has_rich_profile = False

    if website_text:
        tokens = [
            t for t in re.split(r"[^a-z]+", website_text.lower()) if len(t) >= 5
        ]
        freq = Counter(t for t in tokens if t not in _STOPWORDS)
        top_words = {w for w, _ in freq.most_common(50)}
        keyword_fingerprint = frozenset(seeds | top_words)
        has_rich_profile = len(top_words) >= 10

    return {
        "name_lower": name_lower,
        "name_words": name_words,
        "domain": domain,
        "domain_stem": domain_stem,
        "domain_parts": domain_parts,
        "keyword_fingerprint": keyword_fingerprint,
        "has_rich_profile": has_rich_profile,
    }


def _score_article_relevance(
    article: Dict[str, Any],
    company_name: str,
    company_domain: str,
    entity_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Two-dimension article relevance scorer.
    Returns "high", "medium", or "low".

    The central question is not "does this article mention the company name?"
    but "does this article describe the same entity as the target company?"

    ── Dimension 1: entity_match ─────────────────────────────────────────
    Determined by the combination of identity signals below. Name length is
    NOT a criterion — the same logic applies to all companies regardless of
    whether the name has 2, 5, or 20 characters.

    Positive identity signals:
      DEFINITIVE  Article served from the company's own domain.
      STRONG      Company name verbatim in title + vocabulary overlap (≥2 fp kws)
                  OR company name + source domain confirmation.
      CONTEXTUAL  Company name in title + any vocabulary overlap (≥1 fp kw).
      SOURCE-TRUST Company name in title + high-credibility source. Covers generic
                  business headlines ("IRIS raises €5M") that use financial language
                  absent from a technical fingerprint. Only trusted outlets
                  (Reuters, Bloomberg, TechCrunch, major press) qualify.
      UNVERIFIED  Company name in title, no fingerprint available (website not
                  scraped). Cannot confirm or deny — accept conditionally.
      PARAPHRASE  Strong vocabulary alignment (≥3 fp kws) without name. Only
                  meaningful when fingerprint was built from a rich website.
      DOMAIN REF  Company domain stem appears in article's source identifier.

    Negative identity signals:
      CONFLICT    Title contains an entity-type conflict term (e.g. "magazine",
                  "missile") NOT present in the company's own vocabulary.
      PROFILE_MISS Company name in title + rich profile built + ZERO vocabulary
                  overlap. The fingerprint represents the company's distinctive
                  vocabulary. Zero overlap despite a rich profile is strong
                  evidence the article is about a DIFFERENT entity with the same
                  name. Rejected unless the source has high credibility.

    ── Dimension 2: source_credibility ──────────────────────────────────
    Default "medium" for all indexed news. Recognised major outlets (financial
    press, registries, official sources) are upgraded to "high".

    ── Inclusion rule ────────────────────────────────────────────────────
    entity_match HIGH                         → return "high"   (accept)
    entity_match MEDIUM + confirmation†       → return "medium" (accept)
    entity_match LOW                          → return "low"    (reject)

    †confirmation = source_cred="high"  OR  fp_overlap≥1  OR  no fingerprint
      (When entity is "medium" and we have a rich fingerprint showing zero
       vocabulary overlap, only a recognised high-credibility source can
       override. Everything else is rejected.)
    """
    # ── Resolve entity profile ────────────────────────────────────────────
    if entity_profile is None:
        entity_profile = _build_entity_profile("", company_name, company_domain)

    name_lower: str = entity_profile.get("name_lower") or company_name.lower().strip()
    name_words: List[str] = entity_profile.get("name_words") or _name_words(company_name)
    domain_stem: str = entity_profile.get("domain_stem", "")
    fingerprint: frozenset = entity_profile.get("keyword_fingerprint", frozenset())
    has_rich_profile: bool = entity_profile.get("has_rich_profile", False)

    # ── Extract article signals ───────────────────────────────────────────
    title: str = (article.get("title") or "").lower()
    art_domain: str = (article.get("domain") or article.get("source") or "").lower()
    source_name: str = (article.get("source_name") or "").lower()
    combined_source: str = art_domain + " " + source_name

    # ── Dimension 2: source credibility (computed early, used in entity logic) ──
    source_cred = "medium"
    _high_cred_patterns = {
        "reuters", "bloomberg", "ft.com", "wsj.", "nytimes", "economist",
        "techcrunch", "wired", "forbes", "fortune", "businessinsider",
        "expansion.com", "cincodias", "eleconomista", "elconfidencial",
        "lavanguardia", "elpais", "elmundo", "abc.es", "cinco dias",
        ".gov", ".gob.", ".europa.eu", "boe.es", "registradores",
    }
    if any(p in combined_source for p in _high_cred_patterns):
        source_cred = "high"

    # ── Dimension 1: entity match ─────────────────────────────────────────

    # DEFINITIVE: article served from the company's own web domain
    if domain_stem and len(domain_stem) >= 3 and domain_stem in art_domain:
        return "high"

    # Signal A: company name verbatim in title
    name_hit: bool = bool(name_lower) and name_lower in title

    # Signal B: all significant words (≥4 chars) of multi-word name in title
    multiword_hit: bool = len(name_words) >= 2 and all(w in title for w in name_words)

    # Signal B2: first word of multi-word name (≥5 chars) — brand identifier.
    # Always uses the FIRST word (the brand anchor), not the longest or any
    # subsequent word. This prevents generic trailing words like "engineering"
    # or "digital" from acting as brand proxies ("Iris Engineering" → first
    # word "iris" is 4 chars → no primary_word_hit).
    _first_word: str = name_lower.split()[0] if len(name_lower.split()) >= 2 else ""
    primary_word: str = _first_word if len(_first_word) >= 5 else ""
    primary_word_hit: bool = bool(primary_word) and primary_word in title

    # Signal C: company domain stem in article source identifier
    source_domain_hit: bool = bool(
        domain_stem
        and len(domain_stem) >= 4
        and (domain_stem in art_domain or domain_stem in source_name)
    )

    # Signal D: vocabulary alignment between article title and company fingerprint
    fp_overlap: int = 0
    if fingerprint:
        title_tokens = frozenset(
            t for t in re.split(r"[^a-z]+", title) if len(t) >= 5
        )
        # Exclude the company's own name words to avoid trivial self-overlap
        name_word_set = frozenset(w for w in name_lower.split() if len(w) >= 5)
        fp_overlap = len((fingerprint - name_word_set) & title_tokens)

    # Negative signal: entity-type conflict.
    # A conflict is "unresolved" when the term is NOT in the company's fingerprint.
    # Example: "magazine" in title for IRIS Engineering → conflict unless IRIS
    # Engineering's website already contains "magazine" (unlikely for a tech firm).
    # IMPORTANT: match whole words only (word boundary) to avoid substring traps
    # such as "revista" matching inside "entrevista" (Spanish for "interview").
    conflict_in_title = {
        t for t in _ENTITY_CONFLICT_TERMS
        if re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", title)
    }
    unresolved_conflict = bool(conflict_in_title - fingerprint)

    # ── Entity match determination ────────────────────────────────────────

    if unresolved_conflict and not source_domain_hit:
        # Explicit entity-type conflict (publication, weapon, organism, etc.)
        # not explained by the company's own vocabulary.
        entity_match = "low"

    elif name_hit and (fp_overlap >= 2 or source_domain_hit):
        # CONFIRMED: name + strong vocabulary alignment or domain confirmation.
        # The fingerprint "recognises" the article as being in the company's sector.
        entity_match = "high"

    elif name_hit and fp_overlap >= 1:
        # CONTEXTUAL: name + at least one vocabulary keyword from the fingerprint.
        # Article is in the right sector/domain — plausible entity match.
        entity_match = "medium"

    elif name_hit and source_cred == "high":
        # SOURCE-TRUST: major outlet reports the company name.
        # High-credibility sources cover companies with generic business headlines
        # ("IRIS raises €5M Series A") that use financial language not in a
        # technical fingerprint. Trust the outlet's editorial judgement.
        entity_match = "medium"

    elif name_hit and not has_rich_profile:
        # UNVERIFIED: name in title, no fingerprint to check.
        # Website was not scraped — cannot confirm or deny entity.
        entity_match = "medium"

    elif name_hit:
        # PROFILE_MISS: name_hit=True + has_rich_profile=True + fp_overlap=0
        # + not source_cred="high".
        # We built a vocabulary fingerprint from the company's website and this
        # article's title shares NONE of the company's distinctive sector words.
        # This is the primary indicator of a different entity with the same name
        # (e.g. "IRIS Capital" for "IRIS Engineering", "Iris van Herpen" for
        # "IRIS Engineering"). Conservative decision: reject.
        entity_match = "low"

    elif multiword_hit:
        # All significant words of multi-word name in title.
        entity_match = "medium"

    elif primary_word_hit and (fp_overlap >= 1 or source_cred == "high" or not has_rich_profile):
        # Brand word (first word ≥5 chars of multi-word name) present in title.
        # Accepted when at least one of: vocabulary overlap, high-cred source, or
        # no rich fingerprint to contradict (same confirmation logic as name_hit paths).
        # Example: "Mercadona lanza app de pedidos online" for "Mercadona Digital".
        entity_match = "medium"

    elif fp_overlap >= 3 and has_rich_profile:
        # PARAPHRASE: strong vocabulary alignment without explicit name.
        # Occurs when the article headline uses a product/brand synonym.
        # Only meaningful when website content produced the fingerprint.
        entity_match = "medium"

    elif source_domain_hit:
        # Article published on a domain related to the company.
        entity_match = "medium"

    else:
        entity_match = "low"

    # ── Inclusion decision ────────────────────────────────────────────────
    if entity_match == "high":
        return "high"

    if entity_match == "medium":
        # Accept only when there is additional confirmation beyond "name seen":
        #   1. High-credibility source — trust the outlet's editorial quality.
        #   2. Vocabulary overlap ≥1 — fingerprint confirms sector context.
        #   3. No fingerprint available — cannot verify, accept by default.
        if source_cred == "high" or fp_overlap >= 1 or not has_rich_profile:
            return "medium"
        # Medium entity confidence + no fingerprint confirmation + non-notable
        # source → too weak to include. Protects against noise from generic
        # blogs or low-quality news aggregators picking up the company name.
        return "low"

    return "low"


def _is_relevant_article(
    article: Dict[str, Any],
    company_name: str,
    company_domain: str,
    entity_profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Returns True if the article is accepted as relevant for the target company.

    Accepts "high" and "medium" entity_match confidence; rejects "low".
    Pass an entity_profile built via _build_entity_profile (derived from the
    company's own website text) to enable vocabulary-based identity confirmation.
    """
    return _score_article_relevance(
        article, company_name, company_domain, entity_profile
    ) in ("high", "medium")


def _is_wikipedia_relevant(
    wiki: Dict[str, Any],
    company_name: str,
    company_domain: str,
) -> bool:
    """
    Returns True if the Wikipedia article is likely about the target company.
    Protects against homonym contamination (villages, people, concepts).

    Strategy:
    - Title must match the company name.
    - For single-word or short names (most common ambiguity case), require
      that the summary contains business-context terms. The full domain URL
      (e.g. "mercadona.es") in the summary is definitive, but the bare stem
      is NOT used because it equals the company name and appears in any article.
    """
    title = (wiki.get("title") or "").lower()
    summary = (wiki.get("summary") or "").lower()
    name_lower = company_name.lower().strip()

    # Title must contain company name or its significant words
    words = _name_words(company_name)
    title_match = name_lower in title or (words and any(w in title for w in words))
    if not title_match:
        return False

    # Multi-word long names (≥ 2 significant words) are usually unambiguous
    if len(words) >= 2:
        return True

    # Single-word or short names: require business context in summary
    # Full domain URL (not bare stem) appearing in summary is definitive
    if company_domain and company_domain in summary:
        return True

    business_terms = {
        "empresa", "compañía", "sociedad", "company", "corporation", "founded",
        "headquartered", "revenue", "employees", "services", "software",
        "platform", "group", "grupo", "société", "gmbh", "s.a.", "s.l.",
        "ltd", "inc.", "llc", "founded in", "operates", "provider",
        "acquisition", "merger", "billion", "million", "startup",
    }
    return any(term in summary for term in business_terms)


def _compute_evidence_profile(normalized: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classifies the quality and breadth of publicly available evidence for the
    target company, based on already-normalized data. Returns a coverage_tier
    and a structured profile used by scoring modules to graduate caps.

    This is a general heuristic — it references no specific companies.

    Source classes recognised:
      news          — GDELT, Google News (media/press coverage)
      registry      — BORME, OpenCorporates (legal/institutional confirmation)
      institutional — Wikipedia (publicly documented entity)
      technical     — GitHub (open-source/technical footprint)
      market        — SimilarWeb (web traffic/market data)
      hr            — Glassdoor (employer reputation/org data)

    coverage_tier:
      "rich"     — abundant, multi-source evidence; includes press OR strong
                   institutional portfolio (e.g. B2B/niche companies with
                   registry + GitHub + market data but limited press coverage)
      "moderate" — partial external evidence with at least one independent
                   non-self-reported source
      "sparse"   — limited external evidence (mostly website + 1 scraper)
      "minimal"  — website-only or near-zero external signals
    """
    sources = normalized.get("data_sources_used", [])
    external_sources = [s for s in sources if s != "website"]

    # ── News sources (press / media coverage) ────────────────────────────────
    news_count = (
        len(normalized.get("news_articles", []))
        + len(normalized.get("google_news_articles", []))
    )
    has_any_news = news_count >= 1
    has_significant_news = news_count >= 3

    # ── Registry / institutional sources ─────────────────────────────────────
    borme_entries = normalized.get("borme_entries") or []
    has_borme = bool(borme_entries)
    opencorp_legal = bool((normalized.get("corporate_data") or {}).get("legal_name"))
    has_corporate_registry = has_borme or opencorp_legal

    # ── Other independent external sources ───────────────────────────────────
    has_wikipedia = normalized.get("wikipedia_summary") is not None
    has_github = normalized.get("github_data") is not None
    has_market_data = normalized.get("similarweb_data") is not None   # SimilarWeb
    has_glassdoor = normalized.get("glassdoor_data") is not None

    # ── Source-class breakdown ────────────────────────────────────────────────
    # Non-news external: registry/institutional/technical/market sources that
    # provide independent validation without requiring press coverage.
    # These are the primary external validation channel for B2B, industrial,
    # deep-tech, and niche companies that rarely appear in general press.
    _NEWS_SOURCES = {"gdelt", "google_news"}
    non_news_external_sources = [s for s in external_sources if s not in _NEWS_SOURCES]
    non_news_external_count = len(non_news_external_sources)
    has_any_external_non_news = non_news_external_count > 0

    # Any external source (news OR non-news)
    external_source_count = len(external_sources)
    has_any_external = has_any_news or has_any_external_non_news

    # ── Leadership visibility ─────────────────────────────────────────────────
    # Wikipedia → named entity with public profile → leadership likely visible.
    # News ≥2 across ≥2 sources → press mentions often name executives.
    # BORME entries → Spanish commercial registry filings frequently name
    #   directors/officers (e.g. "Nombramiento de administrador único").
    #   Even without structured officer data, BORME confirms legal existence
    #   and can name individuals in filing titles.
    likely_leadership_visible = (
        has_wikipedia
        or (news_count >= 2 and external_source_count >= 2)
        or has_borme  # Registry filings often list named directors/officers
    )

    # ── Coverage tier ─────────────────────────────────────────────────────────
    # Tier is intentionally media-agnostic: a company with strong registry +
    # technical + market footprint qualifies as "rich" or "moderate" even if
    # it has zero press coverage. This correctly handles B2B/industrial/niche
    # companies whose primary external validation channel is not general news.
    if (
        # Classic path: abundant sources including news
        (external_source_count >= 4 and has_significant_news and (has_corporate_registry or has_wikipedia))
        or (external_source_count >= 3 and has_significant_news and has_wikipedia)
        or (external_source_count >= 3 and news_count >= 5 and has_corporate_registry)
        # Press + technical footprint: well-covered SaaS/tech companies (no registry required)
        or (external_source_count >= 3 and has_significant_news and has_any_external_non_news)
        # Institutional path: strong non-news portfolio (B2B/niche/deep-tech, no press)
        or (non_news_external_count >= 3 and has_corporate_registry)
        or (non_news_external_count >= 2 and has_corporate_registry and has_wikipedia)
    ):
        coverage_tier = "rich"
    elif (
        # Standard moderate: news present + at least one more external source
        (external_source_count >= 2 and has_any_news)
        # Institutional moderate: multiple non-news external sources without press
        or (non_news_external_count >= 2)
        # Single institutional + registry confirmation
        or (has_corporate_registry and has_any_external_non_news)
    ):
        coverage_tier = "moderate"
    elif external_source_count >= 1 or has_any_news:
        coverage_tier = "sparse"
    else:
        coverage_tier = "minimal"

    # ── High-visibility floor ──────────────────────────────────────────────────
    # Detects companies whose true public presence clearly exceeds what this
    # scraping pass retrieved. Prevents false "sparse"/"minimal" labels for
    # globally visible entities when scraping gaps reduce retrieved article count.
    #
    # Conditions (must satisfy BOTH halves):
    #   Left:  Wikipedia confirmed → publicly documented notable entity.
    #   Right: SimilarWeb rank < 50,000 (top-tier web traffic)
    #          OR ≥2 articles from high-credibility press outlets.
    #
    # Effect: floors coverage_tier at "moderate". Never downgrades a higher tier.
    # Rationale: a company confirmed by Wikipedia AND showing strong web traffic
    # or credible press coverage cannot genuinely be "sparse" — the pipeline just
    # failed to retrieve enough of the available evidence in this pass.
    _sw_data = normalized.get("similarweb_data") or {}
    try:
        _sw_rank = int(_sw_data.get("global_rank") or 0)
    except (TypeError, ValueError):
        _sw_rank = 0
    _is_high_traffic = 0 < _sw_rank < 50_000

    _HIGH_CRED_PATTERNS = frozenset({
        "reuters", "bloomberg", "ft.com", "wsj.", "nytimes", "economist",
        "techcrunch", "wired", "forbes", "fortune", "businessinsider",
        "expansion", "elpais", "elmundo", "lavanguardia", "cincodias",
        "handelsblatt", "lesmechos", "lefigaro", "corriere",
    })
    _all_scraped = (
        normalized.get("news_articles", [])
        + normalized.get("google_news_articles", [])
    )
    _high_cred_count = sum(
        1 for a in _all_scraped
        if any(p in (a.get("domain") or a.get("source") or "").lower()
               for p in _HIGH_CRED_PATTERNS)
    )
    is_high_visibility = has_wikipedia and (_is_high_traffic or _high_cred_count >= 2)

    if is_high_visibility and coverage_tier in ("sparse", "minimal"):
        coverage_tier = "moderate"

    return {
        # Core tier
        "coverage_tier": coverage_tier,
        # Counts
        "external_source_count": external_source_count,
        "news_article_count": news_count,
        "non_news_external_count": non_news_external_count,
        # Source-class flags
        "has_any_news": has_any_news,
        "has_significant_news": has_significant_news,
        "has_any_external_non_news": has_any_external_non_news,
        "has_any_external": has_any_external,
        "has_corporate_registry": has_corporate_registry,
        "has_borme": has_borme,
        "has_wikipedia": has_wikipedia,
        "has_github": has_github,
        "has_market_data": has_market_data,
        "has_glassdoor": has_glassdoor,
        # Derived signals
        "likely_leadership_visible": likely_leadership_visible,
        "is_high_visibility": is_high_visibility,
    }


def normalize_collected_data(
    collected: Dict[str, Optional[Dict[str, Any]]],
    company_name: str = "",
    company_domain: str = "",
) -> Dict[str, Any]:
    """
    Input: raw outputs from all scrapers (None = scraper failed or was skipped).
    Output: unified normalized dict consumed by LLM modules.
    """
    normalized: Dict[str, Any] = {
        "website_text": "",
        "website_pages": [],
        "corporate_data": {},
        "news_articles": [],        # GDELT
        "google_news_articles": [], # Google News RSS
        "borme_entries": [],
        "wikipedia_summary": None,  # Wikipedia
        "app_store_data": None,     # App Store (iTunes)
        "github_data": None,        # GitHub org
        "similarweb_data": None,    # SimilarWeb
        "glassdoor_data": None,     # Glassdoor
        "references": {},
        "data_sources_used": [],
        "data_quality_warnings": [],  # Discarded/irrelevant sources
        "evidence_profile": {},       # Public evidence quality classification
    }

    website = collected.get("website")
    opencorp = collected.get("opencorporates")
    gdelt = collected.get("gdelt")
    borme = collected.get("borme")
    google_news = collected.get("google_news")
    wikipedia = collected.get("wikipedia")
    app_stores = collected.get("app_stores")
    github = collected.get("github")
    similarweb = collected.get("similarweb")
    glassdoor = collected.get("glassdoor")

    # ── Website ──────────────────────────────────────────────────────────
    if website:
        normalized["data_sources_used"].append("website")
        pages = website.get("pages", [])
        normalized["website_pages"] = [
            {"url": p.get("url"), "title": p.get("title")}
            for p in pages
        ]

        # Build organized text: label each page section individually
        combined = website.get("combined_text", "")
        if combined:
            normalized["website_text"] = combined[:_MAX_WEBSITE_TEXT]
        else:
            # Fallback: concatenate per-page text with source labels
            parts = []
            for p in pages:
                page_text = p.get("text") or p.get("content") or ""
                if page_text:
                    label = f"[PAGE: {p.get('url', '')}]\n"
                    parts.append(label + page_text)
            normalized["website_text"] = "\n\n".join(parts)[:_MAX_WEBSITE_TEXT]

    # ── Entity profile ────────────────────────────────────────────────────
    # Built from website text (already populated above) so it is available
    # for all subsequent article-filtering steps.  Degrades gracefully to
    # name+domain seeds when website text is absent.
    _entity_profile = _build_entity_profile(
        normalized["website_text"],
        company_name,
        company_domain,
    )

    # ── OpenCorporates ────────────────────────────────────────────────────
    if opencorp and opencorp.get("found"):
        normalized["data_sources_used"].append("opencorporates")
        normalized["corporate_data"] = {
            "legal_name": opencorp.get("legal_name"),
            "company_number": opencorp.get("company_number"),
            "jurisdiction": opencorp.get("jurisdiction"),
            "company_type": opencorp.get("company_type"),
            "status": opencorp.get("status"),
            "incorporation_date": opencorp.get("incorporation_date"),
            "registered_address": opencorp.get("registered_address"),
            "opencorporates_url": opencorp.get("opencorporates_url"),
        }

    # ── GDELT ─────────────────────────────────────────────────────────────
    if gdelt and gdelt.get("found"):
        raw_articles = gdelt.get("articles", [])
        if company_name or company_domain:
            relevant = [
                a for a in raw_articles
                if _is_relevant_article(a, company_name, company_domain, _entity_profile)
            ]
            discarded = len(raw_articles) - len(relevant)
            if discarded:
                normalized["data_quality_warnings"].append(
                    f"GDELT: {discarded} article(s) discarded — title did not match "
                    f"company name '{company_name}' or domain '{company_domain}'."
                )
        else:
            relevant = raw_articles
        if relevant:
            normalized["data_sources_used"].append("gdelt")
        normalized["news_articles"] = relevant[:_MAX_NEWS_ITEMS]

    # ── BORME ─────────────────────────────────────────────────────────────
    if borme and borme.get("found"):
        normalized["data_sources_used"].append("borme")
        normalized["borme_entries"] = borme.get("entries", [])

    # ── Google News ───────────────────────────────────────────────────────
    if google_news and google_news.get("found"):
        raw_google = google_news.get("articles", [])
        if company_name or company_domain:
            relevant_google = [
                a for a in raw_google
                if _is_relevant_article(a, company_name, company_domain, _entity_profile)
            ]
            discarded_google = len(raw_google) - len(relevant_google)
            if discarded_google:
                normalized["data_quality_warnings"].append(
                    f"Google News: {discarded_google} article(s) discarded — title did not match "
                    f"company name '{company_name}' or domain '{company_domain}'."
                )
        else:
            relevant_google = raw_google
        if relevant_google:
            normalized["data_sources_used"].append("google_news")
        normalized["google_news_articles"] = relevant_google[:_MAX_NEWS_ITEMS]
    elif google_news and not google_news.get("found"):
        discarded = google_news.get("discarded_count", 0)
        if discarded:
            normalized["data_quality_warnings"].append(
                f"Google News: {discarded} articles were fetched but discarded "
                f"as irrelevant (titles did not match company name or domain)."
            )

    # ── Wikipedia ─────────────────────────────────────────────────────────
    if wikipedia and wikipedia.get("found"):
        if _is_wikipedia_relevant(wikipedia, company_name, company_domain):
            normalized["data_sources_used"].append("wikipedia")
            normalized["wikipedia_summary"] = {
                "title": wikipedia.get("title"),
                "summary": wikipedia.get("summary"),
                # Structured infobox people data (separate from prose summary).
                # Empty string when the infobox fetch failed or found nothing.
                "key_people": wikipedia.get("key_people", ""),
                "url": wikipedia.get("url"),
                "language": wikipedia.get("language"),
            }
        else:
            normalized["data_quality_warnings"].append(
                f"Wikipedia: article '{wikipedia.get('title')}' discarded — "
                f"does not appear to be about the target company '{company_name}'."
            )

    # ── App Stores ────────────────────────────────────────────────────────
    if app_stores and app_stores.get("found"):
        app_confirmed = app_stores.get("confirmed", True)  # legacy scrapers default True
        if app_confirmed:
            normalized["data_sources_used"].append("app_stores")
            normalized["app_store_data"] = app_stores.get("app_store")
        else:
            # Name matches but developer ≠ domain_stem → ambiguous attribution.
            # Keep as unverified signal, not as a primary validated source.
            normalized["data_quality_warnings"].append(
                f"App Store: app '{(app_stores.get('app_store') or {}).get('name', '?')}' "
                f"was found but its developer could not be confirmed as the target company "
                f"— excluded from verified sources."
            )
    elif app_stores and not app_stores.get("found"):
        reason = app_stores.get("discarded_reason")
        if reason == "no_relevance_match":
            normalized["data_quality_warnings"].append(
                "App Store: results were found but discarded — no app name or "
                "developer matched the company name or domain."
            )

    # ── GitHub ────────────────────────────────────────────────────────────
    if github and github.get("found"):
        normalized["data_sources_used"].append("github")
        normalized["github_data"] = {
            "login": github.get("login"),
            "org_url": github.get("org_url"),
            "public_repos": github.get("public_repos"),
            "stars_total": github.get("stars_total"),
            "top_repos": github.get("repos", [])[:5],
        }
    elif github and not github.get("found"):
        reason = github.get("discarded_reason")
        if reason == "no_relevance_match":
            normalized["data_quality_warnings"].append(
                "GitHub: organizations were found in search results but discarded — "
                "none had sufficient name similarity to the company (threshold: 0.6)."
            )

    # ── SimilarWeb ────────────────────────────────────────────────────────
    if similarweb and similarweb.get("found"):
        normalized["data_sources_used"].append("similarweb")
        normalized["similarweb_data"] = {
            "global_rank": similarweb.get("global_rank"),
            "category": similarweb.get("category"),
            "top_country": similarweb.get("top_country"),
            "monthly_visits_estimate": similarweb.get("monthly_visits_estimate"),
        }

    # ── Glassdoor ─────────────────────────────────────────────────────────
    if glassdoor and glassdoor.get("found"):
        normalized["data_sources_used"].append("glassdoor")
        normalized["glassdoor_data"] = {
            "overall_rating": glassdoor.get("overall_rating"),
            "review_count": glassdoor.get("review_count"),
            "recommend_pct": glassdoor.get("recommend_pct"),
            "ceo_approval_pct": glassdoor.get("ceo_approval_pct"),
        }

    # ── References list (for report block E) ─────────────────────────────
    # Uses already-filtered normalized data so discarded/homonym sources
    # never appear in the references block.
    normalized["references"] = {
        "sources": _build_references(
            website=website,
            opencorp=opencorp,
            borme=borme,
            filtered_news=normalized["news_articles"],
            filtered_google=normalized["google_news_articles"],
            filtered_wikipedia=normalized["wikipedia_summary"],
            filtered_app_store=normalized["app_store_data"],
            filtered_github=normalized["github_data"],
        )
    }

    # ── Evidence profile (must run last, after all sources are resolved) ──
    normalized["evidence_profile"] = _compute_evidence_profile(normalized)

    return normalized


def _build_references(
    website: Optional[Dict[str, Any]],
    opencorp: Optional[Dict[str, Any]],
    borme: Optional[Dict[str, Any]],
    filtered_news: Optional[List[Dict[str, Any]]] = None,
    filtered_google: Optional[List[Dict[str, Any]]] = None,
    filtered_wikipedia: Optional[Dict[str, Any]] = None,
    filtered_app_store: Optional[Dict[str, Any]] = None,
    filtered_github: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Build references using ALREADY-FILTERED data only.
    News, Wikipedia, App Store and GitHub receive the post-relevance-check
    values from the normalized dict, so homonym/irrelevant sources are never
    included here.
    """
    refs: List[Dict[str, str]] = []

    if website:
        for page in website.get("pages", []):
            if page.get("url"):
                refs.append({
                    "title": page.get("title") or "Company website",
                    "url": page["url"],
                    "source_type": "website",
                })

    if opencorp and opencorp.get("opencorporates_url"):
        refs.append({
            "title": f"OpenCorporates — {opencorp.get('legal_name', '')}",
            "url": opencorp["opencorporates_url"],
            "source_type": "opencorporates",
        })

    # Wikipedia: only present if it passed _is_wikipedia_relevant()
    if filtered_wikipedia and filtered_wikipedia.get("url"):
        refs.append({
            "title": f"Wikipedia — {filtered_wikipedia.get('title', '')}",
            "url": filtered_wikipedia["url"],
            "source_type": "wikipedia",
        })

    # GDELT: already filtered by _is_relevant_article()
    for article in (filtered_news or [])[:5]:
        if article.get("url"):
            refs.append({
                "title": article.get("title") or "News article (GDELT)",
                "url": article["url"],
                "source_type": "gdelt",
            })

    # Google News: already filtered by scraper's relevance check
    for article in (filtered_google or [])[:5]:
        if article.get("url"):
            refs.append({
                "title": article.get("title") or "News article (Google News)",
                "url": article["url"],
                "source_type": "google_news",
            })

    if borme and borme.get("entries"):
        for entry in borme["entries"][:3]:
            if entry.get("url"):
                refs.append({
                    "title": entry.get("title") or "BORME entry",
                    "url": entry["url"],
                    "source_type": "borme",
                })

    # App Store: only present if it passed relevance check
    if filtered_app_store and filtered_app_store.get("url"):
        refs.append({
            "title": f"App Store — {filtered_app_store.get('name', '')}",
            "url": filtered_app_store["url"],
            "source_type": "app_stores",
        })

    # GitHub: only present if it passed relevance check
    if filtered_github and filtered_github.get("org_url"):
        refs.append({
            "title": f"GitHub — {filtered_github.get('login', '')}",
            "url": filtered_github["org_url"],
            "source_type": "github",
        })

    return refs
