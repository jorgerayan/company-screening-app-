"""
LLM Module 7 — Competitive positioning analysis.
Identifies main competitors, market position, real vs perceived advantages,
competitive threats, and relevant sector trends.
"""
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.gemini_client import gemini_client
from app.models.llm_result import LLMResult
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_OUTPUT_SCHEMA = """
{
  "main_competitors": [
    {
      "name": "string — competitor name",
      "competitor_type": "direct | adjacent | large_comparable | substitute_technology | integrator | alternative_solution",
      "basis": "string — 1-2 sentences explaining the competitive overlap and why this type was chosen",
      "source": "website | google_news | gdelt | sector_knowledge",
      "evidence_type": "verified_fact | reasonable_inference | unverifiable"
    }
  ],
  "market_position": "leader | challenger | niche | follower | unknown",
  "position_analysis": "REQUIRED: Minimum 300 words of analytical prose. Assess the company's competitive standing: what market it competes in, who the main players are, how this company is positioned relative to them, what the competitive dynamics look like, and what this implies for a potential acquirer.",
  "real_vs_perceived_advantages": "REQUIRED: 2-3 sentences distinguishing between advantages clearly supported by evidence vs those that appear to be marketing claims without verification.",
  "competitive_threats": [
    "string — MINIMUM 3 items. Each 2-3 sentences describing a specific competitive threat relevant to this company."
  ],
  "sector_trends": "REQUIRED: 3-4 sentences on macro trends (technology shifts, regulatory changes, market consolidation, new entrants) specifically relevant to this company's sector and geography.",
  "differentiation_score": "high | medium | low | unclear",
  "differentiation_basis": "string — 2-3 sentences explaining the differentiation_score with specific evidence.",
  "confidence": "high | medium | low",
  "data_limitations": "string | null — what competitive intelligence is missing from public sources and why it matters."
}
"""


_LANG_OPENERS = {
    "es": "Eres un analista experto en M&A. DEBES responder EXCLUSIVAMENTE en español. Todos los campos de texto en el JSON deben estar en español.",
    "en": "You are an expert M&A analyst. Respond in English.",
    "fr": "Tu es un analyste M&A expert. Tu DOIS répondre EXCLUSIVEMENT en français. Tous les champs texte du JSON doivent être en français.",
    "de": "Du bist ein M&A-Experte. Du MUSST AUSSCHLIESSLICH auf Deutsch antworten. Alle Textfelder im JSON müssen auf Deutsch sein.",
    "it": "Sei un analista M&A esperto. DEVI rispondere ESCLUSIVAMENTE in italiano. Tutti i campi di testo nel JSON devono essere in italiano.",
}


_LABELS = {
    "es": {
        "company": "PERFIL DE LA EMPRESA",
        "biz_model": "CONTEXTO DEL MODELO DE NEGOCIO",
        "website": "CONTENIDO WEB (buscar: menciones de competidores, afirmaciones de mercado, lenguaje de posicionamiento)",
        "similarweb": "DATOS DE TRÁFICO WEB (SimilarWeb — contexto competitivo)",
        "gdelt": "NOTICIAS DE GDELT (pueden mencionar dinámicas competitivas)",
        "google_news": "NOTICIAS DE GOOGLE NEWS (pueden mencionar competidores o tendencias del sector)",
        "no_website": "Sin contenido web disponible.",
        "no_gdelt": "No se encontraron artículos de GDELT.",
        "no_google": "No se encontraron artículos de Google News.",
        "instructions": "Analiza el panorama competitivo con rigor. Solo nombra competidores con evidencia.\nposition_analysis: MÍNIMO 300 palabras.\ncompetitive_threats: MÍNIMO 3 elementos, 2-3 frases cada uno.\nsector_trends: 3-4 frases, específicas para el mercado de esta empresa.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "company": "COMPANY PROFILE",
        "biz_model": "BUSINESS MODEL CONTEXT",
        "website": "WEBSITE CONTENT (scan for competitor mentions, market claims, positioning language)",
        "similarweb": "SIMILARWEB TRAFFIC DATA (competitive context)",
        "gdelt": "NEWS FROM GDELT (may mention competitive dynamics)",
        "google_news": "NEWS FROM GOOGLE NEWS (may mention competitors or sector trends)",
        "no_website": "No website content available.",
        "no_gdelt": "No GDELT articles found.",
        "no_google": "No Google News articles found.",
        "instructions": "Analyze the competitive landscape with rigor. Only name competitors with evidence.\nposition_analysis: MINIMUM 300 words.\ncompetitive_threats: MINIMUM 3 items, 2-3 sentences each.\nsector_trends: 3-4 sentences, specific to this company's market.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "company": "PROFIL DE L'ENTREPRISE",
        "biz_model": "CONTEXTE DU MODÈLE D'AFFAIRES",
        "website": "CONTENU DU SITE WEB (rechercher : mentions de concurrents, affirmations de marché, langage de positionnement)",
        "similarweb": "DONNÉES DE TRAFIC WEB (SimilarWeb — contexte concurrentiel)",
        "gdelt": "ACTUALITÉS DE GDELT (peuvent mentionner des dynamiques concurrentielles)",
        "google_news": "ACTUALITÉS DE GOOGLE NEWS (peuvent mentionner des concurrents ou des tendances sectorielles)",
        "no_website": "Aucun contenu de site web disponible.",
        "no_gdelt": "Aucun article GDELT trouvé.",
        "no_google": "Aucun article Google News trouvé.",
        "instructions": "Analysez le paysage concurrentiel avec rigueur. Ne nommez des concurrents qu'avec des preuves.\nposition_analysis : MINIMUM 300 mots.\ncompetitive_threats : MINIMUM 3 éléments, 2-3 phrases chacun.\nsector_trends : 3-4 phrases, spécifiques au marché de cette entreprise.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "company": "UNTERNEHMENSPROFIL",
        "biz_model": "GESCHÄFTSMODELLKONTEXT",
        "website": "WEBSITE-INHALT (suche nach: Wettbewerbserwähnungen, Marktbehauptungen, Positionierungssprache)",
        "similarweb": "WEB-TRAFFIC-DATEN (SimilarWeb — Wettbewerbskontext)",
        "gdelt": "NACHRICHTEN VON GDELT (können Wettbewerbsdynamiken erwähnen)",
        "google_news": "NACHRICHTEN VON GOOGLE NEWS (können Wettbewerber oder Branchentrends erwähnen)",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "no_gdelt": "Keine GDELT-Artikel gefunden.",
        "no_google": "Keine Google-News-Artikel gefunden.",
        "instructions": "Analysiere die Wettbewerbslandschaft mit Sorgfalt. Nenne Wettbewerber nur mit Beweisen.\nposition_analysis: MINDESTENS 300 Wörter.\ncompetitive_threats: MINDESTENS 3 Einträge, je 2-3 Sätze.\nsector_trends: 3-4 Sätze, spezifisch für den Markt dieses Unternehmens.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "company": "PROFILO AZIENDALE",
        "biz_model": "CONTESTO DEL MODELLO DI BUSINESS",
        "website": "CONTENUTO DEL SITO WEB (cerca: menzioni di concorrenti, affermazioni di mercato, linguaggio di posizionamento)",
        "similarweb": "DATI TRAFFICO WEB (SimilarWeb — contesto competitivo)",
        "gdelt": "NOTIZIE DA GDELT (possono menzionare dinamiche competitive)",
        "google_news": "NOTIZIE DA GOOGLE NEWS (possono menzionare concorrenti o tendenze del settore)",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "no_gdelt": "Nessun articolo GDELT trovato.",
        "no_google": "Nessun articolo Google News trovato.",
        "instructions": "Analizza il panorama competitivo con rigore. Nomina i concorrenti solo con prove.\nposition_analysis: MINIMO 300 parole.\ncompetitive_threats: MINIMO 3 elementi, 2-3 frasi ciascuno.\nsector_trends: 3-4 frasi, specifiche per il mercato di questa azienda.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    return f"""{opener}

You are a senior M&A analyst writing the competitive positioning section of a company
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
- Do NOT invent competitor names. Only name competitors if they are explicitly mentioned in
  the data, or if they are universally well-known players in the clearly identified sector.
  Mark each competitor's evidence_type accurately.
- The "position_analysis" field must be minimum 300 words of analytical prose.
- "market_position" must be justified by specific evidence — do not default to "unknown"
  if there are meaningful signals.
- "competitive_threats" must be specific to this company and sector, not generic.
- "sector_trends" must be 3-4 sentences on macro trends relevant to THIS company.
- Distinguish carefully between real, defensible competitive advantages and marketing claims.

COMPETITOR TYPE CLASSIFICATION (required for every entry in main_competitors):
Classify each competitor using one of the following types — do NOT mark all as "direct":
- "direct": competes for the same customers with a substantially similar product or service
  at the same tier. The customer would evaluate both on the same RFP.
- "adjacent": overlapping addressable market but different core offering. Could expand into
  direct competition but is not a head-to-head competitor today.
- "large_comparable": large company or group operating in the same broad space. Not a direct
  target-level competitor but relevant for market context and benchmarking. Often indicates
  sector maturity or fragmentation.
- "substitute_technology": a different technology or approach that solves the same underlying
  customer problem without competing on the same product axis.
- "integrator": platform, suite, or systems integrator that bundles competing or substitute
  functionality as part of a broader offer.
- "alternative_solution": non-product or indirect alternative (e.g. doing it in-house, using
  manual processes, hiring consultants). Relevant when the market is immature or switching
  costs from the status quo are the real competitive barrier.
Select the most accurate type for each competitor. Use "basis" to explain the overlap and
justify the type choice. A healthy competitive landscape entry will contain a mix of types.

EPISTEMIC DISCIPLINE:
- "differentiation_score" MUST be "unclear" if differentiation is based solely on
  self-reported website claims with no external corroboration (press, analyst, customer).
- "market_position" MUST NOT assert "leader", "dominant", or "strong position" without
  citing a specific external source (news article, analyst report, customer review).
  Use "self-reported: [claim]" or "not independently verified" when sourcing only the website.
- Never invent market share estimates. If no data is available, state that explicitly.
- "competitive_threats" must acknowledge uncertainty when sector intelligence is limited.
- If no press coverage is available, do NOT write "market position is unknown" — analyze
  available signals (website positioning, sector knowledge, SimilarWeb, client segments)
  to reason about competitive standing, clearly labeling inferences as such."""


async def run_competitive_position(
    classification: Dict[str, Any],
    business_model: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    website_text = normalized_data.get("website_text", "")[:8_000]
    news = normalized_data.get("news_articles", [])
    google_news = normalized_data.get("google_news_articles", [])
    similarweb = normalized_data.get("similarweb_data")

    import json
    news_json = json.dumps(news[:8], ensure_ascii=False, indent=2)
    google_news_json = json.dumps(google_news[:8], ensure_ascii=False, indent=2)

    l = _LABELS.get(language or "es", _LABELS["es"])

    similarweb_section = ""
    if similarweb:
        similarweb_section = f"""
{l['similarweb']}:
- Global rank: #{similarweb.get('global_rank', 'unknown')}
- Category rank: {similarweb.get('category', 'unknown')}
- Monthly visits estimate: {similarweb.get('monthly_visits_estimate', 'unknown')}
- Top country: {similarweb.get('top_country', 'unknown')}
"""

    user_prompt = f"""
{l['company']}:
- Name: {classification.get('factual_profile', {}).get('name', 'unknown')}
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- Subsector: {classification.get('subsector', 'unknown')}
- B2B/B2C: {classification.get('b2b_or_b2c', 'unknown')}
- Geography: {classification.get('geography', [])}
- Main product/service: {classification.get('main_product_or_service', 'unknown')}
- Value proposition: {classification.get('value_proposition_summary', 'unknown')}

{l['biz_model']}:
- Model type: {business_model.get('model_type', 'unknown')}
- Differentiation: {business_model.get('differentiation', 'none apparent')}
- Barriers to entry: {business_model.get('barriers_to_entry', 'none apparent')}
- Competitive landscape (from business model module): {business_model.get('competitive_landscape', 'unknown')}
- Scalability: {business_model.get('scalability', 'unknown')}

{l['website']}:
---
{website_text if website_text else l['no_website']}
---
{similarweb_section}
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
        expected_keys=["main_competitors", "market_position", "position_analysis", "competitive_threats", "confidence"],
        language=language,
    )

    data = result["data"]

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="competitive_position",
        input_payload={
            "business_type": classification.get("business_type"),
            "sector": classification.get("sector"),
            "model_type": business_model.get("model_type"),
            "website_chars": len(website_text),
        },
        output_payload=data,
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return data
