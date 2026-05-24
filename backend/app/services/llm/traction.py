"""
LLM Module 3 — Traction signals analysis.
"""
import json
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.gemini_client import gemini_client
from app.models.llm_result import LLMResult
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_OUTPUT_SCHEMA = """
{
  "signals": [
    {
      "type": "hiring | press | product_launch | expansion | partnership | award | customer_case_study | funding | legal_event | regulatory | web_traffic | app_store | github_activity | other",
      "title": "short descriptive title (5-8 words)",
      "evidence": "REQUIRED: 2-3 sentences describing exactly what was observed and from which source.",
      "interpretation": "REQUIRED: minimum 3 sentences — what does this signal mean for the company's trajectory?",
      "source": "website | gdelt | borme | opencorporates | google_news | github | app_stores | similarweb",
      "date": "date or null",
      "confidence": "high | medium | low",
      "evidence_type": "verified_fact | reasonable_inference | unverifiable"
    }
  ],
  "growth_narrative": "REQUIRED: minimum 400 words. Thorough analytical assessment of the traction picture.",
  "news_summary": "3-4 sentence paragraph on media coverage, or null if zero articles found.",
  "internal_vs_external_consistency": "REQUIRED: 3-4 sentence credibility assessment.",
  "data_availability": "rich | moderate | sparse",
  "data_gaps": "REQUIRED: minimum 3 sentences on missing signals and their investment implications.",
  "overall_confidence": "high | medium | low",
  "notes": "string or null"
}
"""


_LANG_OPENERS = {
    "es": "Eres un analista experto en M&A. DEBES responder EXCLUSIVAMENTE en español. Todos los campos de texto en el JSON deben estar en español.",
    "en": "You are an expert M&A analyst. Respond in English.",
    "fr": "Tu es un analyste M&A expert. Tu DOIS répondre EXCLUSIVEMENT en français. Tous les champs texte du JSON doivent être en français.",
    "de": "Du bist ein M&A-Experte. Du MUSST AUSSCHLIESSLICH auf Deutsch antworten. Alle Textfelder im JSON müssen auf Deutsch sein.",
    "it": "Sei un analista M&A esperto. DEVI rispondere ESCLUSIVAMENTE in italiano. Tutti i campi di testo nel JSON devono essere in italiano.",
}

_LANG_NAMES = {
    "es": "español",
    "en": "English",
    "fr": "français",
    "de": "Deutsch",
    "it": "italiano",
}

_LANG_ABSOLUTE_RULES = {
    "es": (
        "REGLA ABSOLUTA: Todo el JSON de respuesta debe estar en español. "
        "Los campos 'growth_narrative', 'title', 'evidence', 'interpretation', "
        "'internal_vs_external_consistency', 'data_gaps', 'notes' deben estar en español. "
        "Si el contenido fuente está en inglés, TRADÚCELO al español. "
        "No escribas ni una sola palabra en inglés."
    ),
    "en": (
        "ABSOLUTE RULE: All JSON response fields must be in English. "
        "Fields 'growth_narrative', 'title', 'evidence', 'interpretation', "
        "'internal_vs_external_consistency', 'data_gaps', 'notes' must be in English."
    ),
    "fr": (
        "RÈGLE ABSOLUE: Tous les champs JSON de la réponse doivent être en français. "
        "Les champs 'growth_narrative', 'title', 'evidence', 'interpretation', "
        "'internal_vs_external_consistency', 'data_gaps', 'notes' doivent être en français. "
        "Si le contenu source est en anglais, TRADUIS-LE en français. "
        "N'écris pas un seul mot en anglais."
    ),
    "de": (
        "ABSOLUTE REGEL: Alle JSON-Antwortfelder müssen auf Deutsch sein. "
        "Die Felder 'growth_narrative', 'title', 'evidence', 'interpretation', "
        "'internal_vs_external_consistency', 'data_gaps', 'notes' müssen auf Deutsch sein. "
        "Wenn der Quellinhalt auf Englisch ist, ÜBERSETZE ihn ins Deutsche. "
        "Schreibe kein einziges Wort auf Englisch."
    ),
    "it": (
        "REGOLA ASSOLUTA: Tutti i campi JSON della risposta devono essere in italiano. "
        "I campi 'growth_narrative', 'title', 'evidence', 'interpretation', "
        "'internal_vs_external_consistency', 'data_gaps', 'notes' devono essere in italiano. "
        "Se il contenuto sorgente è in inglese, TRADUCILO in italiano. "
        "Non scrivere nemmeno una parola in inglese."
    ),
}


def _build_system_prompt(language: str) -> str:
    lang = language or "es"
    opener = _LANG_OPENERS.get(lang, _LANG_OPENERS["es"])
    absolute_rule = _LANG_ABSOLUTE_RULES.get(lang, _LANG_ABSOLUTE_RULES["es"])
    return f"""{opener}

{absolute_rule}

You are a senior business analyst evaluating public traction signals for a company
as part of an investor pre-screening process. Your job is to find, interpret, and
contextualize every available signal of company activity, growth, and market presence.

You are writing a professional M&A screening report section that will be used by investors
and acquirers to make real decisions. Your analysis must be exhaustive, well-reasoned and
based on all available evidence. Each section must be substantive — minimum 300 words of
analytical prose. Never truncate your analysis. If you have evidence, analyze it in depth.
If you lack evidence, explain specifically what is missing, why it matters for an acquisition
decision, and what the absence implies about the company.

Your analysis must be thorough, detailed and professional. Write like a junior M&A analyst
preparing a first screening report. Never summarize when you can analyze. Never use a bullet
point when prose is more informative.

Strict rules:
- Work strictly with the data provided. Do NOT invent signals or events.
- Each signal's "interpretation" must be minimum 3 sentences.
- The growth_narrative must be minimum 400 words.
- If signals are sparse, write a thorough analysis of what is absent and what it implies.
- Distinguish between company self-claims and independently confirmed external signals.
- The data_gaps field must cover each major missing data type with specific relevance.

EXTRACTION VS EXISTENCE DISTINCTION (non-negotiable):
When external news articles are absent from the provided data, the correct framing depends
on the PIPELINE CONTEXT block (see user prompt):

ESTABLISHED COMPANY (PIPELINE CONTEXT shows "Established company = YES"):
- news_summary: state "No media items were retrieved by the current data pipeline" or
  "No press coverage was extracted by the pipeline for this analysis run."
  Do NOT write: "No media coverage exists", "The company has no press presence",
  "No external news coverage was found" (implies genuine absence).
- data_gaps: flag the empty news retrieval as a PIPELINE RETRIEVAL LIMITATION:
  "External news retrieval returned no results for this company. Given the company's
  apparent public profile, this is likely a pipeline/scraping limitation rather than
  evidence of low media visibility. External press coverage should be verified manually."
- data_availability: base this on all available signals, not solely on news count.
  A company with app store data, Wikipedia, or SimilarWeb is NOT "sparse" even if
  news retrieval is empty.

NON-ESTABLISHED COMPANY (PIPELINE CONTEXT shows "Established company = NO"):
- Normal analysis: empty news genuinely reflects limited external coverage.
  Write: "No external press coverage was identified." Standard framing applies.

GENERAL RULE: Absence in extracted data ≠ absence in reality.
For companies with strong footprint signals (Wikipedia, large app store, international
operations, known brand), treat any data gap as potentially pipeline-driven before
treating it as evidence of business weakness."""


_LABELS = {
    "es": {
        "company": "EMPRESA EN ANÁLISIS",
        "website": "CONTENIDO WEB (declaraciones propias de la empresa)",
        "gdelt": "NOTICIAS DE GDELT (medios externos)",
        "google_news": "NOTICIAS DE GOOGLE NEWS",
        "borme": "REGISTRO MERCANTIL (BORME)",
        "github": "DATOS DE LA ORGANIZACIÓN EN GITHUB",
        "appstore": "DATOS DE APP STORE (Apple App Store / iTunes)",
        "similarweb": "DATOS DE TRÁFICO WEB (SimilarWeb)",
        "no_website": "Sin contenido web disponible.",
        "no_gdelt": "No se encontraron artículos en GDELT.",
        "no_google": "No se encontraron artículos en Google News.",
        "no_borme": "No se encontraron entradas en BORME.",
        "instructions": "Analiza cada señal disponible con rigor. Interpretación por señal: mínimo 3 frases.\ngrowth_narrative: MÍNIMO 400 palabras. Si hay pocas señales, analiza en profundidad qué está ausente.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "company": "COMPANY BEING ANALYZED",
        "website": "WEBSITE CONTENT (company's own statements)",
        "gdelt": "NEWS from GDELT (external media)",
        "google_news": "NEWS from GOOGLE NEWS",
        "borme": "CORPORATE REGISTRY (BORME)",
        "github": "GITHUB ORGANIZATION DATA",
        "appstore": "APP STORE DATA (Apple App Store / iTunes)",
        "similarweb": "SIMILARWEB TRAFFIC DATA",
        "no_website": "No website content available.",
        "no_gdelt": "No news articles found in GDELT.",
        "no_google": "No Google News articles found.",
        "no_borme": "No BORME entries found.",
        "instructions": "Analyze every available signal carefully. Interpretation per signal: minimum 3 sentences.\ngrowth_narrative: MINIMUM 400 words. If sparse, analyze what is absent in depth.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "company": "ENTREPRISE EN COURS D'ANALYSE",
        "website": "CONTENU DU SITE WEB (déclarations de l'entreprise)",
        "gdelt": "ACTUALITÉS DE GDELT (médias externes)",
        "google_news": "ACTUALITÉS DE GOOGLE NEWS",
        "borme": "REGISTRE DES SOCIÉTÉS (BORME)",
        "github": "DONNÉES DE L'ORGANISATION GITHUB",
        "appstore": "DONNÉES APP STORE (Apple App Store / iTunes)",
        "similarweb": "DONNÉES DE TRAFIC WEB (SimilarWeb)",
        "no_website": "Aucun contenu de site web disponible.",
        "no_gdelt": "Aucun article trouvé dans GDELT.",
        "no_google": "Aucun article Google News trouvé.",
        "no_borme": "Aucune entrée BORME trouvée.",
        "instructions": "Analysez chaque signal disponible avec rigueur. Interprétation par signal : minimum 3 phrases.\ngrowth_narrative : MINIMUM 400 mots. Si peu de signaux, analysez en profondeur ce qui est absent.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "company": "ZU ANALYSIERENDE FIRMA",
        "website": "WEBSITE-INHALT (eigene Aussagen des Unternehmens)",
        "gdelt": "NACHRICHTEN VON GDELT (externe Medien)",
        "google_news": "NACHRICHTEN VON GOOGLE NEWS",
        "borme": "HANDELSREGISTER (BORME)",
        "github": "GITHUB-ORGANISATIONSDATEN",
        "appstore": "APP-STORE-DATEN (Apple App Store / iTunes)",
        "similarweb": "WEB-TRAFFIC-DATEN (SimilarWeb)",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "no_gdelt": "Keine Artikel in GDELT gefunden.",
        "no_google": "Keine Google-News-Artikel gefunden.",
        "no_borme": "Keine BORME-Einträge gefunden.",
        "instructions": "Analysiere alle verfügbaren Signale sorgfältig. Interpretation pro Signal: mindestens 3 Sätze.\ngrowth_narrative: MINDESTENS 400 Wörter. Falls wenig Signale, analysiere gründlich, was fehlt.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "company": "AZIENDA IN ANALISI",
        "website": "CONTENUTO DEL SITO WEB (dichiarazioni dell'azienda)",
        "gdelt": "NOTIZIE DA GDELT (media esterni)",
        "google_news": "NOTIZIE DA GOOGLE NEWS",
        "borme": "REGISTRO DELLE IMPRESE (BORME)",
        "github": "DATI ORGANIZZAZIONE GITHUB",
        "appstore": "DATI APP STORE (Apple App Store / iTunes)",
        "similarweb": "DATI TRAFFICO WEB (SimilarWeb)",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "no_gdelt": "Nessun articolo trovato in GDELT.",
        "no_google": "Nessun articolo Google News trovato.",
        "no_borme": "Nessuna voce BORME trovata.",
        "instructions": "Analizza ogni segnale disponibile con rigore. Interpretazione per segnale: minimo 3 frasi.\ngrowth_narrative: MINIMO 400 parole. Se i segnali sono scarsi, analizza in profondità cosa manca.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


async def run_traction(
    classification: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    news = normalized_data.get("news_articles", [])
    google_news = normalized_data.get("google_news_articles", [])
    borme = normalized_data.get("borme_entries", [])
    website_text = normalized_data.get("website_text", "")[:6_000]
    github = normalized_data.get("github_data")
    app_store = normalized_data.get("app_store_data")
    similarweb = normalized_data.get("similarweb_data")
    l = _LABELS.get(language or "es", _LABELS["es"])

    news_json = json.dumps(news[:10], ensure_ascii=False, indent=2)
    google_news_json = json.dumps(google_news[:10], ensure_ascii=False, indent=2)
    borme_json = json.dumps(borme[:5], ensure_ascii=False, indent=2)

    # ── Established company detection ──────────────────────────────────────
    # Drives framing of absent news: pipeline limitation vs genuine absence.
    _evidence_profile = normalized_data.get("evidence_profile") or {}
    _listing_status = (classification.get("listing_status") or "unknown").lower()
    _total_news = len(news) + len(google_news)
    _is_established = (
        bool(normalized_data.get("wikipedia_summary"))
        or _evidence_profile.get("is_high_visibility", False)
        or _evidence_profile.get("coverage_tier") in ("rich", "moderate")
        or _total_news >= 2
        or bool(app_store)
    )

    github_section = ""
    if github:
        top_repos = github.get("top_repos", [])[:3]
        github_section = f"""
{l['github']}:
- Organization: {github.get('login')} ({github.get('org_url')})
- Public repositories: {github.get('public_repos', 'unknown')}
- Total stars across repos: {github.get('stars_total', 0)}
- Top repos: {json.dumps(top_repos, ensure_ascii=False)}
"""

    app_store_section = ""
    if app_store:
        app_store_section = f"""
{l['appstore']}:
- App name: {app_store.get('name')}
- Rating: {app_store.get('rating')} / 5 ({app_store.get('rating_count')} reviews)
- Last updated: {app_store.get('last_updated')}
- Developer: {app_store.get('developer')}
"""

    similarweb_section = ""
    if similarweb:
        similarweb_section = f"""
{l['similarweb']}:
- Global rank: #{similarweb.get('global_rank', 'unknown')}
- Category: {similarweb.get('category', 'unknown')}
- Top country: {similarweb.get('top_country', 'unknown')}
- Monthly visits estimate: {similarweb.get('monthly_visits_estimate', 'unknown')}
"""

    user_prompt = f"""
PIPELINE CONTEXT (drives extraction interpretation rules — read before analyzing):
- Established company (Wikipedia / coverage / app store / high-visibility signals): {'YES — apply EXTRACTION VS EXISTENCE DISTINCTION rule' if _is_established else 'NO — standard analysis'}
- Listing status: {_listing_status}
- Wikipedia available: {'YES' if normalized_data.get("wikipedia_summary") else 'NO'}
- News articles retrieved (GDELT + Google News): {_total_news}
- App store data available: {'YES' if app_store else 'NO'}
- SimilarWeb data available: {'YES' if similarweb else 'NO'}
{f"- SANITY WARNING: established company but zero news retrieved — frame as pipeline limitation, NOT as evidence of no media presence." if _is_established and _total_news == 0 else ""}---

{l['company']}:
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- Geography: {classification.get('geography', [])}
- Main product/service: {classification.get('main_product_or_service', 'unknown')}

{l['website']}:
---
{website_text if website_text else l['no_website']}
---

{l['gdelt']}:
{news_json if news else l['no_gdelt']}

{l['google_news']}:
{google_news_json if google_news else l['no_google']}

{l['borme']}:
{borme_json if borme else l['no_borme']}
{github_section}{app_store_section}{similarweb_section}
{l['instructions']}

{l['schema']}
{_OUTPUT_SCHEMA}
"""

    result = await gemini_client.generate_structured(
        system_prompt=_build_system_prompt(language),
        user_prompt=user_prompt,
        expected_keys=["signals", "growth_narrative", "data_availability", "data_gaps"],
        language=language,
    )

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="traction",
        input_payload={
            "news_article_count": len(news),
            "borme_entry_count": len(borme),
            "website_chars": len(website_text),
        },
        output_payload=result["data"],
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return result["data"]
