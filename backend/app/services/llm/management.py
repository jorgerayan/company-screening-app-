"""
LLM Module 6 — Management team and founders analysis.
Analyzes publicly detectable executives, founders, leadership stability,
and public reputation of the leadership team.
"""
import re as _re
import unicodedata as _ud
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.gemini_client import gemini_client
from app.models.llm_result import LLMResult
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Sentinel written by the Wikipedia scraper when infobox people data is found.
_WIKI_INFOBOX_SENTINEL = "[Wikipedia infobox — key people]"


def _norm_name(s: str) -> str:
    """Accent-strip + lowercase — used for deduplication across accent variants."""
    return _ud.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _parse_key_people_lines(block: str) -> List[Dict[str, Any]]:
    """
    Parse a block of "field: value" lines from a Wikipedia infobox into
    executive dicts.  Works on both:
      - the raw key_people string stored on wikipedia_summary["key_people"]
      - the block extracted from the sentinel-embedded summary string
    Returns [] if nothing useful found.
    """
    executives: List[Dict[str, Any]] = []
    seen: set = set()

    for line in block.strip().split("\n"):
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if not value:
            continue

        if field in ("founders", "founder"):
            names = [
                n.strip()
                for n in _re.split(r",\s*|\s+(?:and|y|et|und|e)\s+", value)
                if n.strip()
            ]
            for name in names:
                if name and _norm_name(name) not in seen:
                    seen.add(_norm_name(name))
                    executives.append({
                        "name": name,
                        "role": "Founder",
                        "background": "Named as company founder in Wikipedia infobox.",
                        "source": "wikipedia",
                        "evidence_type": "verified_fact",
                    })

        elif field in ("ceo", "chairman", "president", "director_general"):
            role_label = {
                "ceo": "CEO", "chairman": "Chairman",
                "president": "President", "director_general": "Director General",
            }.get(field, field.title())
            for name in [n.strip() for n in _re.split(r",\s*", value) if n.strip()]:
                if name and _norm_name(name) not in seen:
                    seen.add(_norm_name(name))
                    executives.append({
                        "name": name,
                        "role": role_label,
                        "background": f"Named as {role_label} in Wikipedia infobox.",
                        "source": "wikipedia",
                        "evidence_type": "verified_fact",
                    })

        elif field == "key_people":
            # "key_people: Name (Role), Name (Role)"
            for entry in _re.split(r",\s*(?=[A-ZÁÉÍÓÚÜÑ])", value):
                entry = entry.strip()
                if not entry:
                    continue
                nm = _re.match(r"^(.+?)\s*\((.+?)\)\s*$", entry)
                name, role = (nm.group(1).strip(), nm.group(2).strip()) if nm else (entry, "Key Person")
                if name and _norm_name(name) not in seen:
                    seen.add(_norm_name(name))
                    executives.append({
                        "name": name,
                        "role": role,
                        "background": "Named in Wikipedia infobox key_people field.",
                        "source": "wikipedia",
                        "evidence_type": "verified_fact",
                    })

    return executives


def _executives_from_wiki_infobox(wiki_summary: str) -> List[Dict[str, Any]]:
    """
    Sentinel-based extraction: used when key_people field is unavailable.
    Looks for the '[Wikipedia infobox — key people]' block embedded in the
    summary by the scraper and delegates to _parse_key_people_lines().
    """
    if _WIKI_INFOBOX_SENTINEL not in wiki_summary:
        return []
    m = _re.search(
        r"\[Wikipedia infobox — key people\]\n(.+?)\n\n\[Wikipedia article text\]",
        wiki_summary,
        _re.DOTALL,
    )
    return _parse_key_people_lines(m.group(1)) if m else []


def _founders_from_prose(prose: str) -> List[Dict[str, Any]]:
    """
    Last-resort prose extraction: find "founded by X and Y" / "fundada por X y Y"
    patterns in Wikipedia article text when the infobox fetch failed.
    Conservative — requires proper-cased multi-word names to reduce false positives.
    Returns [] if nothing found.
    """
    # Strip infobox block if present (already covered by key_people / sentinel path)
    text = prose
    if _WIKI_INFOBOX_SENTINEL in text:
        _, _, text = text.partition("[Wikipedia article text]\n")

    # Primary patterns: "founded by X and Y" / "fundada por X y Y"
    primary_patterns = [
        # English: "founded in 2015 by Oscar Pierre and Sacha Michaud"
        r"founded(?:\s+in\s+\d{4})?\s+by\s+"
        r"([A-ZÁÉÍÓÚÜ][a-záéíóúü]+(?:\s+[A-ZÁÉÍÓÚÜ][a-záéíóúü]+)+)"
        r"(?:\s+and\s+([A-ZÁÉÍÓÚÜ][a-záéíóúü]+(?:\s+[A-ZÁÉÍÓÚÜ][a-záéíóúü]+)+))?",
        # Spanish: "fundada en 2014 por Oscar Pierre y Sacha Michaud"
        r"fundad[ao](?:\s+en\s+\d{4})?\s+por\s+"
        r"([A-ZÁÉÍÓÚÜ][a-záéíóúü]+(?:\s+[A-ZÁÉÍÓÚÜ][a-záéíóúü]+)+)"
        r"(?:\s+y\s+([A-ZÁÉÍÓÚÜ][a-záéíóúü]+(?:\s+[A-ZÁÉÍÓÚÜ][a-záéíóúü]+)+))?",
    ]
    # Supplementary: co-founders introduced via pronoun in the founding sentence.
    # e.g. "fundada...por Oscar Pierre y lanzada...por él mismo y Sacha Michaud"
    # or   "founded by Oscar Pierre and launched...by him and Sacha Michaud"
    # Only run when the primary pattern found at least one name (same text context).
    pronoun_patterns = [
        r"(?:él mismo|ella misma|ellos mismos|ellas mismas)\s+y\s+"
        r"([A-ZÁÉÍÓÚÜ][a-záéíóúü]+(?:\s+[A-ZÁÉÍÓÚÜ][a-záéíóúü]+)+)",
        r"(?:himself|herself|themselves)\s+and\s+"
        r"([A-ZÁÉÍÓÚÜ][a-záéíóúü]+(?:\s+[A-ZÁÉÍÓÚÜ][a-záéíóúü]+)+)",
    ]

    executives: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(name: str) -> None:
        if name and len(name) > 3 and _norm_name(name) not in seen:
            seen.add(_norm_name(name))
            executives.append({
                "name": name,
                "role": "Founder",
                "background": "Named as company founder in Wikipedia article text.",
                "source": "wikipedia",
                "evidence_type": "reasonable_inference",
            })

    for pattern in primary_patterns:
        for m in _re.finditer(pattern, text):
            _add((m.group(1) or "").strip())
            _add((m.group(2) or "").strip())
        if executives:
            break  # Stop at first matching language

    # If primary found at least one name, run supplementary pronoun scan
    # to capture co-founders mentioned in a consecutive clause.
    if executives:
        for pattern in pronoun_patterns:
            for m in _re.finditer(pattern, text):
                _add(m.group(1).strip())

    return executives

_OUTPUT_SCHEMA = """
{
  "executives": [
    {
      "name": "string — full name as found in sources",
      "role": "string — title or role",
      "background": "string — 2-3 sentences on detectable experience, previous companies, education",
      "source": "website | wikipedia | google_news | gdelt | borme | opencorporates",
      "evidence_type": "verified_fact | reasonable_inference | unverifiable"
    }
  ],
  "leadership_analysis": "REQUIRED: Minimum 300 words. Analytical assessment of the leadership team: seniority, experience quality, domain fit, gaps, what the profile implies for an acquirer.",
  "founder_profile": "string | null — if founders are identifiable: who they are, their background, and what their founder profile implies for retention and culture post-acquisition.",
  "team_stability": "stable | uncertain | signs_of_instability | unknown",
  "stability_analysis": "REQUIRED: 2-3 sentences explaining the basis for the team_stability rating with specific evidence.",
  "public_reputation": "string | null — any notable public presence, media mentions of executives, speaking engagements, or public statements that reflect on leadership quality.",
  "recent_changes": "string | null — any detected recent changes in leadership (new CEO, departures, restructurings) and what they imply for an acquirer.",
  "red_flags": [
    "string — ONLY include if grounded in specific evidence. Each item 1-2 sentences."
  ],
  "confidence": "high | medium | low",
  "data_limitations": "string | null — specific gaps: what public data is missing, why it matters for acquisition decisions."
}
"""


_LANG_OPENERS = {
    "es": "Eres un analista experto en M&A. DEBES responder EXCLUSIVAMENTE en español. Todos los campos de texto en el JSON deben estar en español.",
    "en": "You are an expert M&A analyst. You MUST respond EXCLUSIVELY in English. All JSON text fields must be in English.",
    "fr": "Tu es un analyste M&A expert. Tu DOIS répondre EXCLUSIVEMENT en français. Tous les champs texte du JSON doivent être en français.",
    "de": "Du bist ein M&A-Experte. Du MUSST AUSSCHLIESSLICH auf Deutsch antworten. Alle Textfelder im JSON müssen auf Deutsch sein.",
    "it": "Sei un analista M&A esperto. DEVI rispondere ESCLUSIVAMENTE in italiano. Tutti i campi di testo nel JSON devono essere in italiano.",
}

_LANG_ABSOLUTE_RULES = {
    "es": (
        "REGLA ABSOLUTA: Todo el JSON de respuesta debe estar escrito en español. "
        "Esto incluye sin excepción: leadership_analysis, founder_profile, stability_analysis, "
        "public_reputation, recent_changes, data_limitations, y todos los campos de tipo string "
        "dentro de 'executives' y 'red_flags'. Está terminantemente prohibido mezclar idiomas. "
        "Si el contenido de las fuentes está en otro idioma, tradúcelo al español en tu respuesta."
    ),
    "en": (
        "ABSOLUTE RULE: All JSON response fields must be written in English. "
        "This includes without exception: leadership_analysis, founder_profile, stability_analysis, "
        "public_reputation, recent_changes, data_limitations, and all string fields inside "
        "'executives' and 'red_flags'. Language mixing is strictly forbidden."
    ),
    "fr": (
        "RÈGLE ABSOLUE: Tous les champs JSON de la réponse doivent être rédigés en français. "
        "Cela inclut sans exception: leadership_analysis, founder_profile, stability_analysis, "
        "public_reputation, recent_changes, data_limitations, et tous les champs de type chaîne "
        "dans 'executives' et 'red_flags'. Mélanger les langues est strictement interdit."
    ),
    "de": (
        "ABSOLUTE REGEL: Alle JSON-Antwortfelder müssen auf Deutsch verfasst sein. "
        "Dies gilt ausnahmslos für: leadership_analysis, founder_profile, stability_analysis, "
        "public_reputation, recent_changes, data_limitations und alle String-Felder in "
        "'executives' und 'red_flags'. Sprachmischung ist streng verboten."
    ),
    "it": (
        "REGOLA ASSOLUTA: Tutti i campi JSON della risposta devono essere scritti in italiano. "
        "Ciò include senza eccezioni: leadership_analysis, founder_profile, stability_analysis, "
        "public_reputation, recent_changes, data_limitations e tutti i campi stringa all'interno "
        "di 'executives' e 'red_flags'. Mescolare le lingue è severamente vietato."
    ),
}


_LABELS = {
    "es": {
        "company": "PERFIL DE LA EMPRESA",
        "website": "CONTENIDO WEB (buscar: nombres, roles, secciones Sobre Nosotros/Equipo/Gobierno)",
        "wikipedia": "RESUMEN DE WIKIPEDIA (fuente externa autorizada)",
        "gdelt": "NOTICIAS DE GDELT (pueden mencionar directivos)",
        "google_news": "NOTICIAS DE GOOGLE NEWS (pueden mencionar directivos o cambios de liderazgo)",
        "borme": "REGISTRO MERCANTIL — BORME (fuente registral oficial — los títulos de los actos frecuentemente nombran a administradores y apoderados)",
        "corporate": "DATOS DE REGISTRO DE EMPRESAS (OpenCorporates / registro equivalente)",
        "no_website": "Sin contenido web disponible.",
        "no_wikipedia": "",
        "no_gdelt": "No se encontraron artículos de GDELT.",
        "no_google": "No se encontraron artículos de Google News.",
        "no_borme": "",
        "instructions": "Analiza TODAS las fuentes disponibles para detectar directivos, fundadores y señales de liderazgo.\n- Extrae nombres y roles de páginas Sobre Nosotros/Equipo/Gobierno si están presentes.\n- Extrae nombres de titulares de noticias y artículos.\n- Extrae nombres de actos del BORME (p.ej. 'Nombramiento de administrador único: Nombre Apellido').\n- Busca cambios de liderazgo, salidas o nuevos nombramientos.\n- Si no se detectan nombres, explica exhaustivamente qué implica esto para un adquirente.\nleadership_analysis: MÍNIMO 300 palabras de prosa analítica.\nred_flags: SOLO si están fundamentados en evidencia específica, no genéricos.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "company": "COMPANY PROFILE",
        "website": "WEBSITE CONTENT (scan for names, roles, About/Team/Governance sections)",
        "wikipedia": "WIKIPEDIA SUMMARY (authoritative external source)",
        "gdelt": "NEWS FROM GDELT (may mention executives)",
        "google_news": "NEWS FROM GOOGLE NEWS (may mention executives or leadership changes)",
        "borme": "COMMERCIAL REGISTRY — BORME (official registry filings — filing titles frequently name directors and officers)",
        "corporate": "COMPANY REGISTRY DATA (OpenCorporates / equivalent registry)",
        "no_website": "No website content available.",
        "no_wikipedia": "",
        "no_gdelt": "No GDELT news articles found.",
        "no_google": "No Google News articles found.",
        "no_borme": "",
        "instructions": "Analyze EVERY available data source for detectable executives, founders, and leadership signals.\n- Extract names and roles from the website About/Team/Governance pages if present.\n- Extract names from news headlines and articles.\n- Extract names from BORME filing titles (e.g. 'Nombramiento de administrador único: First Last').\n- Look for leadership changes, departures, or new appointments in news.\n- If no names are detectable, explain thoroughly what this means for an acquirer.\nleadership_analysis: MINIMUM 300 words of analytical prose.\nred_flags: ONLY if grounded in specific evidence, not generic.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "company": "PROFIL DE L'ENTREPRISE",
        "website": "CONTENU DU SITE WEB (rechercher : noms, rôles, sections À propos/Équipe/Gouvernance)",
        "wikipedia": "RÉSUMÉ WIKIPEDIA (source externe faisant autorité)",
        "gdelt": "ACTUALITÉS DE GDELT (peuvent mentionner des dirigeants)",
        "google_news": "ACTUALITÉS DE GOOGLE NEWS (peuvent mentionner des dirigeants ou des changements de direction)",
        "borme": "REGISTRE DU COMMERCE — BORME (actes officiels — les titres mentionnent souvent des directeurs et mandataires)",
        "corporate": "DONNÉES DU REGISTRE D'ENTREPRISES (OpenCorporates / registre équivalent)",
        "no_website": "Aucun contenu de site web disponible.",
        "no_wikipedia": "",
        "no_gdelt": "Aucun article GDELT trouvé.",
        "no_google": "Aucun article Google News trouvé.",
        "no_borme": "",
        "instructions": "Analysez TOUTES les sources disponibles pour détecter les dirigeants, fondateurs et signaux de leadership.\nleadership_analysis : MINIMUM 300 mots de prose analytique.\nred_flags : UNIQUEMENT si fondés sur des preuves spécifiques, pas génériques.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "company": "UNTERNEHMENSPROFIL",
        "website": "WEBSITE-INHALT (suche nach: Namen, Rollen, Über uns/Team/Governance-Bereichen)",
        "wikipedia": "WIKIPEDIA-ZUSAMMENFASSUNG (maßgebliche externe Quelle)",
        "gdelt": "NACHRICHTEN VON GDELT (können Führungskräfte erwähnen)",
        "google_news": "NACHRICHTEN VON GOOGLE NEWS (können Führungskräfte oder Führungswechsel erwähnen)",
        "borme": "HANDELSREGISTER — BORME (offizielle Registereintragungen — Titel nennen oft Direktoren und Bevollmächtigte)",
        "corporate": "UNTERNEHMENSREGISTERDATEN (OpenCorporates / entsprechendes Register)",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "no_wikipedia": "",
        "no_gdelt": "Keine GDELT-Artikel gefunden.",
        "no_google": "Keine Google-News-Artikel gefunden.",
        "no_borme": "",
        "instructions": "Analysiere ALLE verfügbaren Quellen auf erkennbare Führungskräfte, Gründer und Leadership-Signale.\nleadership_analysis: MINDESTENS 300 Wörter analytischer Prosa.\nred_flags: NUR wenn in spezifischen Beweisen begründet, nicht generisch.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "company": "PROFILO AZIENDALE",
        "website": "CONTENUTO DEL SITO WEB (cerca: nomi, ruoli, sezioni Chi siamo/Team/Governance)",
        "wikipedia": "RIASSUNTO WIKIPEDIA (fonte esterna autorevole)",
        "gdelt": "NOTIZIE DA GDELT (possono menzionare dirigenti)",
        "google_news": "NOTIZIE DA GOOGLE NEWS (possono menzionare dirigenti o cambiamenti di leadership)",
        "borme": "REGISTRO COMMERCIALE — BORME (atti ufficiali — i titoli spesso nominano direttori e procuratori)",
        "corporate": "DATI DEL REGISTRO AZIENDALE (OpenCorporates / registro equivalente)",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "no_wikipedia": "",
        "no_gdelt": "Nessun articolo GDELT trovato.",
        "no_google": "Nessun articolo Google News trovato.",
        "no_borme": "",
        "instructions": "Analizza TUTTE le fonti disponibili per rilevare dirigenti, fondatori e segnali di leadership.\nleadership_analysis: MINIMO 300 parole di prosa analitica.\nred_flags: SOLO se fondati su prove specifiche, non generici.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


def _build_system_prompt(language: str) -> str:
    lang = language or "es"
    opener = _LANG_OPENERS.get(lang, _LANG_OPENERS["es"])
    absolute_rule = _LANG_ABSOLUTE_RULES.get(lang, _LANG_ABSOLUTE_RULES["es"])
    return f"""{opener}

{absolute_rule}

You are a senior M&A analyst writing the management team section of a company
pre-screening report for an investor or acquirer.

You are writing a professional M&A screening report section that will be used by investors
and acquirers to make real decisions. Your analysis must be exhaustive, well-reasoned and
based on all available evidence. Each section must be substantive — minimum 300 words of
analytical prose. Never truncate your analysis. If you have evidence, analyze it in depth.
If you lack evidence, explain specifically what is missing, why it matters for an acquisition
decision, and what the absence implies about the company.

Your analysis must be thorough, detailed and professional. Write like a junior M&A analyst
preparing a first screening report. Never summarize when you can analyze.

Strict rules:
- Work ONLY with the data provided: company website, Wikipedia, Google News, and press articles.
- Do NOT invent names, roles, or biographies.
- Do NOT mention LinkedIn as a source or limitation. LinkedIn is not available and must not be referenced.
- Only use the data provided from the company website, Wikipedia, Google News, and press articles.
  If executive information is not found in these sources, state that it was not found in publicly
  available sources without mentioning LinkedIn.
- CRITICAL — TESTIMONIALS AND CLIENT QUOTES ARE NOT EXECUTIVES: Do NOT extract persons mentioned
  in client testimonials, customer reviews, partner quotes, case studies, or third-party press
  releases as members of the target company's management team. A Bimbo VP, an Europastry director,
  or any person identified as a customer, client, or external partner is NOT an executive of the
  company being analyzed. Only extract persons who are explicitly identified as employees or
  officers OF the company itself (e.g. "our CEO", "founder of [Company]", "Director at [Company]").
- If a person is mentioned in the website, news, or Wikipedia, extract their role and background
  ONLY if they are clearly identified as belonging to the target company.
- The "leadership_analysis" field must be minimum 300 words of analytical prose.
- For each executive found, provide their name, role, and any detectable background.
- The "team_stability" field must be evidence-based, not assumed.
- If no executives are detectable, explain why and what this implies for an acquirer.
- "red_flags" must be specific, grounded in evidence, not generic warnings.
- "data_limitations" must explain concretely what public data is absent and why it matters,
  without referencing LinkedIn or any unavailable platform.

GOVERNANCE SOURCE PRIORITIZATION:
When scanning data, look beyond simple "About/Team" sections. Leadership information
often appears in sources that require active attention:
WEBSITE: "Governance", "Board of Directors", "Supervisory Board", "Management Board",
  "Investor Relations", "Annual Report", "Corporate Governance", "IR",
  "Group Structure", "Executive Committee", "Leadership Team", "Directors",
  "Legal Notice" (Impressum / Aviso Legal) — often contains registered company officers,
  Press releases announcing appointments, earnings, or strategic decisions.
WIKIPEDIA: infoboxes or biography sections listing named executives or founders.
NEWS/PRESS: headlines that name individuals in leadership roles ("CEO", "founder", "director").
BORME (Spanish commercial registry): filing titles frequently name directors by role and full
  name (e.g. "Nombramiento de administrador único: Juan García López"). Extract any name
  mentioned in BORME filing titles or descriptions as a registry-confirmed officer.
  Use source="borme" and evidence_type="verified_fact" for names extracted from BORME.
Scan ALL available content before concluding that executives are "not identified". A company
with BORME entries, Wikipedia coverage, or press mentions should rarely produce an empty
executives list — look harder in the provided data before reporting absence.

EPISTEMIC LANGUAGE FOR EXECUTIVES:
When the source of an executive's name is the company's own website, use evidence_type="verified_fact"
only if the person is explicitly identified as a current employee/officer of the target company.
If a person is named in a news article but their role is not explicitly stated, use
evidence_type="reasonable_inference" and explain what the source says.
Never use evidence_type="verified_fact" for a name extracted from a client testimonial or
third-party press release where the person is not a target-company employee.

EPISTEMIC DISCIPLINE:
- Only list executives whose names appear explicitly in the provided data sources.
- "team_depth" must be marked "unknown" if no org chart, team page, or press mentions
  of specific personnel are available.
- Do NOT infer team stability, tenure, or retention risk unless there is direct evidence.
- If no executives are publicly identifiable, behaviour depends on company type:
  ESTABLISHED COMPANY (DETECTION CONTEXT shows "Established company = YES"):
    leadership_analysis MUST frame this as a pipeline/extraction limitation:
    "Leadership information was not successfully extracted from the available data.
    For a company with this public footprint, this represents a retrieval limitation —
    executive names likely exist in public sources but were not retrieved by the current
    pipeline. This should be treated as an extraction gap, not evidence of leadership
    absence or instability."
    Do NOT write "no executives found", "key-person risk due to unknown leadership",
    or "succession uncertainty" as if leadership genuinely does not exist publicly.
  NON-ESTABLISHED COMPANY (DETECTION CONTEXT shows "Established company = NO"):
    state clearly that no executives were detected and explain what this implies for
    an acquirer: key-person risk, succession uncertainty, governance opacity.
- "data_limitations" for extraction failures on established companies must use wording like:
  "Executive extraction incomplete — pipeline retrieval limitation, not genuine absence.
  Requires verification against public sources (LinkedIn, company website, news)."
  NOT: "No executives found" or "Leadership cannot be identified".

WIKIPEDIA EXECUTIVE EXTRACTION GUIDE:
Wikipedia articles frequently contain executive information that differs from the website.
Scan specifically for these patterns when Wikipedia content is available:
- Infobox "Key people" field: e.g. "key_people = Oscar Pierre (CEO), Sacha Michaud (Co-CEO)"
- Infobox "founders" / "founder" field: e.g. "founders: Oscar Pierre, Sacha Michaud"
- Opening paragraph: "Company X was founded by [Name] and [Name] in [year]..."
- "Leadership", "Management", "Board of Directors" subsection headings
- Historical CEO/founder mentions in background or timeline sections
- Founder biographies linked from the company article
If Wikipedia is provided and contains any of these patterns, you MUST extract them.
Returning an empty executives list when Wikipedia is available and contains names IS AN ANALYTICAL ERROR.
Use source="wikipedia" and evidence_type="verified_fact" for names extracted from Wikipedia.

FOUNDER EXTRACTION RULE (MANDATORY):
If any data source identifies the company's founders by name (Wikipedia infobox, Wikipedia
opening paragraph, press article, or company website), you MUST list each founder in the
`executives` array — do NOT place them only in `founder_profile`.
Use role = "Founder" (or their known current title if stated), source = "wikipedia" /
"website" / "google_news" as appropriate, and evidence_type = "verified_fact".
You do NOT need to confirm that the founder is currently active to include them.
Founding a company is a permanent, verifiable fact — list the name with its founding role
and note any uncertainty about current status in the `background` field.
The `founder_profile` text field is a narrative complement, not a substitute for listing
founders in `executives`. If you have both a current executive AND a founding context for
the same person, use their current title as role and note the founding context in background.

ESTABLISHED COMPANY DETECTION RULE:
If the DETECTION CONTEXT block in the user prompt marks "Established company = YES", this means
the company has Wikipedia, press, or registry coverage — it is publicly identifiable.
For established companies, these rules are MANDATORY:
1. Exhaustive search in ALL provided sources before concluding executives "not found".
2. If no executives are found after exhaustive search: data_limitations MUST explicitly state
   "DETECTION LIMITATION — this is a known company; executive names likely exist in public
   sources but were not successfully extracted from the data provided."
3. team_stability for established companies with no found executives = "unknown"
   (absence of successful extraction ≠ instability, do not penalise with "signs_of_instability").
4. confidence = "low" when detection failure occurs for an established company.

LANGUAGE REMINDER: Every single text field in your JSON response must be in {lang.upper()}.
Do not write a single sentence in English or any other language unless the target language IS English."""


async def run_management(
    classification: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    import json

    website_text = normalized_data.get("website_text", "")[:12_000]
    news = normalized_data.get("news_articles", [])
    google_news = normalized_data.get("google_news_articles", [])
    wikipedia = normalized_data.get("wikipedia_summary")
    glassdoor = normalized_data.get("glassdoor_data")

    # Registry sources — primary leadership evidence for companies with low press visibility
    borme_entries = normalized_data.get("borme_entries") or []
    corporate_data = normalized_data.get("corporate_data") or {}

    # Use up to 10 news articles per source: larger press archives for visible companies
    # improve chances of finding executive mentions in non-lead articles.
    news_json = json.dumps(news[:10], ensure_ascii=False, indent=2)
    google_news_json = json.dumps(google_news[:10], ensure_ascii=False, indent=2)

    l = _LABELS.get(language or "es", _LABELS["es"])

    # Established-company detection: drives detection-context block and post-processing.
    # Extended beyond Wikipedia/press/BORME to capture companies with clear operational
    # scale (large startups, delivery platforms, SaaS with international presence) even
    # when those registries/scrapers returned no data.
    evidence_profile = normalized_data.get("evidence_profile") or {}
    _coverage_tier = evidence_profile.get("coverage_tier", "sparse")
    _app_data = normalized_data.get("app_store_data") or {}
    _geo = classification.get("geography") or []
    _listing = (classification.get("listing_status") or "unknown").lower()
    _is_established = (
        bool(wikipedia)                                                  # Wikipedia page retrieved
        or evidence_profile.get("is_high_visibility", False)             # normalizer high-visibility flag
        or _coverage_tier in ("rich", "moderate")                        # rich overall evidence coverage
        or evidence_profile.get("news_article_count", 0) >= 2            # external press coverage
        or bool(borme_entries)                                           # Spanish commercial registry
        or _listing == "public"                                          # stock-exchange listed company
        or bool(normalized_data.get("similarweb_data"))                  # significant web traffic data
        or bool(normalized_data.get("github_data"))                      # public code / tech presence
        or (isinstance(_geo, list) and len(_geo) >= 3)                   # multi-country operation
        or (_app_data.get("rating_count") or 0) >= 10_000                  # established app presence (10k+ ratings filters out small/niche apps)
    )

    wikipedia_section = ""
    if wikipedia:
        # 5,000 chars — large company Wikipedia articles often have leadership info
        # after the first 2,000 chars (founding, current CEO, board members, etc.)
        wikipedia_section = f"""
{l['wikipedia']}:
Title: {wikipedia.get('title')}
Summary: {wikipedia.get('summary', '')[:5_000]}
---
"""

    # Glassdoor section: CEO approval rating can serve as a proxy signal for
    # whether the CEO identity is publicly known and their reputation.
    glassdoor_section = ""
    if glassdoor:
        glassdoor_section = f"""
GLASSDOOR (employer reputation signal — use as context for leadership assessment):
- Overall rating: {glassdoor.get('overall_rating', 'N/A')} / 5
- CEO approval: {glassdoor.get('ceo_approval_pct', 'N/A')}%
- Reviews: {glassdoor.get('review_count', 'N/A')}
---
"""

    # BORME section: registry filings frequently name directors/officers in the filing title.
    # e.g. "Nombramiento de administrador único: Juan García López"
    borme_section = ""
    if borme_entries:
        borme_lines = []
        for entry in borme_entries[:10]:
            title = entry.get("title") or ""
            date = entry.get("date") or ""
            url = entry.get("url") or ""
            line = f"- [{date}] {title}"
            if url:
                line += f" ({url})"
            borme_lines.append(line)
        borme_section = f"""
{l['borme']}:
{chr(10).join(borme_lines)}
---
"""

    # Corporate registry section: legal name, jurisdiction, status, incorporation date
    corporate_section = ""
    if corporate_data.get("legal_name"):
        corporate_section = f"""
{l['corporate']}:
- Legal name: {corporate_data.get('legal_name')}
- Jurisdiction: {corporate_data.get('jurisdiction', 'unknown')}
- Type: {corporate_data.get('company_type', 'unknown')}
- Status: {corporate_data.get('status', 'unknown')}
- Incorporated: {corporate_data.get('incorporation_date', 'unknown')}
---
"""

    user_prompt = f"""
DETECTION CONTEXT (read before analyzing — drives mandatory detection rules):
- Established company (Wikipedia / press / registry confirmed): {'YES — apply ESTABLISHED COMPANY DETECTION RULE' if _is_established else 'NO — standard analysis'}
- Coverage tier: {_coverage_tier}
- Wikipedia available: {'YES' if wikipedia else 'NO'}
- Press articles (GDELT + Google News): {len(news) + len(google_news)}
- Registry entries (BORME): {len(borme_entries)}
---

{l['company']}:
- Name: {classification.get('factual_profile', {}).get('name', 'unknown')}
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- Geography: {classification.get('geography', [])}

{l['website']}:
---
{website_text if website_text else l['no_website']}
---
{wikipedia_section}{glassdoor_section}{borme_section}{corporate_section}
{l['gdelt']}:
{news_json if news else l['no_gdelt']}

{l['google_news']}:
{google_news_json if google_news else l['no_google']}

{l['instructions']}

{l['schema']}
{_OUTPUT_SCHEMA}
"""

    result = await gemini_client.generate_structured(
        system_prompt=_build_system_prompt(language),
        user_prompt=user_prompt,
        expected_keys=["executives", "leadership_analysis", "team_stability", "confidence"],
        language=language,
    )

    data = result["data"]

    # ── Diagnostic logging: trace what the LLM returned ───────────────────────
    _llm_exec_count = len(data.get("executives") or [])
    _llm_fp_preview = (data.get("founder_profile") or "")[:120]
    _wiki_has_infobox = wikipedia and _WIKI_INFOBOX_SENTINEL in (wikipedia.get("summary") or "")
    logger.info(
        "management LLM response: executives=%d founder_profile_len=%d "
        "wiki_infobox_block=%s analysis_id=%s",
        _llm_exec_count, len(_llm_fp_preview), _wiki_has_infobox, analysis_id,
    )

    # ── Deterministic fallback: inject executives from Wikipedia ─────────────
    # When the LLM returns an empty executives list, attempt three sources in
    # priority order (all use only data already fetched — no invention):
    #   1. key_people field  — direct structured data from MediaWiki infobox API
    #   2. sentinel in summary — fallback if key_people field is missing (old data)
    #   3. prose "founded by" regex — last resort if infobox fetch failed
    if not data.get("executives") and wikipedia:
        _wiki_sum = wikipedia.get("summary") or ""
        _infobox_execs = (
            _parse_key_people_lines(wikipedia.get("key_people") or "")
            or _executives_from_wiki_infobox(_wiki_sum)
            or _founders_from_prose(_wiki_sum)
        )
        if _infobox_execs:
            data["executives"] = _infobox_execs
            logger.info(
                "management: deterministic wiki injection — added %d executive(s) "
                "(key_people=%r sentinel=%s prose_fallback used) analysis_id=%s",
                len(_infobox_execs),
                bool(wikipedia.get("key_people")),
                _WIKI_INFOBOX_SENTINEL in _wiki_sum,
                analysis_id,
            )

    # ── Post-processing: flag detection failures for established companies ─────
    # If the company has external coverage (Wikipedia, press, registry) but the LLM
    # returned no executives, this is a detection/extraction failure — not genuine
    # absence. Flag it explicitly so downstream modules do not treat it as "no data".
    if not data.get("executives"):
        # Reuse the extended _is_established computed above — same data, same logic.
        # Avoids a second divergent computation and keeps both uses in sync.
        _is_known_company = _is_established
        if _is_known_company:
            _detection_flags = {
                "es": (
                    "LIMITACIÓN DE DETECCIÓN — empresa con cobertura pública (Wikipedia, prensa o registro) "
                    "pero sin directivos extraídos. Esto indica un fallo de extracción, NO ausencia real "
                    "de liderazgo identificable. Se recomienda revisión manual de las fuentes disponibles."
                ),
                "en": (
                    "DETECTION LIMITATION — company with public coverage (Wikipedia, press, or registry) "
                    "but no executives extracted. This indicates an extraction failure, NOT a genuine absence "
                    "of identifiable leadership. Manual review of available sources is recommended."
                ),
                "fr": (
                    "LIMITATION DE DÉTECTION — entreprise avec couverture publique mais sans dirigeants extraits. "
                    "Cela indique un échec d'extraction, pas une absence réelle de leadership identifiable. "
                    "Révision manuelle recommandée."
                ),
                "de": (
                    "ERKENNUNGSLIMITIERUNG — bekanntes Unternehmen ohne extrahierte Führungskräfte. "
                    "Dies ist ein Extraktionsfehler, keine echte Abwesenheit von identifizierbarem Leadership. "
                    "Manuelle Überprüfung empfohlen."
                ),
                "it": (
                    "LIMITAZIONE DI RILEVAMENTO — azienda con copertura pubblica ma senza dirigenti estratti. "
                    "Indica un fallimento di estrazione, non assenza reale di leadership identificabile. "
                    "Si raccomanda revisione manuale."
                ),
            }
            _flag = _detection_flags.get(language or "es", _detection_flags["es"])
            _prior = data.get("data_limitations") or ""
            # Avoid duplication: if the LLM already wrote the detection flag
            # (because the system prompt told it the company is established),
            # overwrite with the deterministic copy rather than prepending a
            # second instance.
            if _flag[:40].lower() in _prior.lower():
                data["data_limitations"] = _flag
            else:
                data["data_limitations"] = _flag + (" " + _prior if _prior else "")
            data["confidence"] = "low"
            logger.warning(
                "management: detection failure for known company — "
                "has_wiki=%s news=%d borme=%d analysis_id=%s",
                bool(wikipedia), len(news) + len(google_news), len(borme_entries), analysis_id,
            )

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="management",
        input_payload={
            "business_type": classification.get("business_type"),
            "sector": classification.get("sector"),
            "website_chars": len(website_text),
            "news_count": len(news),
            "google_news_count": len(google_news),
            "has_wikipedia": bool(wikipedia),
            "has_borme": bool(borme_entries),
            "borme_entry_count": len(borme_entries),
            "has_glassdoor": bool(glassdoor),
        },
        output_payload=data,
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return data
