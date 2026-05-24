"""
LLM Module 1 — Business classifier and factual profiler.
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
  "business_type": "SaaS | marketplace | agency | ecommerce | retail | supermarket | restaurant | hospitality | real_estate | logistics | manufacturing | B2B services | consultancy | industrial | platform | financial services | healthcare | other",
  "sector": "string — primary sector (e.g. HR Tech, Logistics, Construction, Legal, etc.)",
  "subsector": "string or null — more specific niche if determinable",
  "geography": ["list of countries or regions where the company operates or targets"],
  "b2b_or_b2c": "B2B | B2C | B2B2C | both | unknown",
  "main_product_or_service": "string — 3-4 sentences describing the core offering in analytical terms.",
  "value_proposition_summary": "string — 3-4 sentences covering the pain point, the solution, and the claimed outcome.",
  "listing_status": "public | private | startup | subsidiary | unknown",
  "confidence": "high | medium | low",
  "evidence_type": "verified_fact | reasonable_inference | unverifiable",
  "factual_profile": {
    "name": "string",
    "website": "string — URL",
    "activity": "string — REQUIRED: Minimum 3 full analytical paragraphs. First: what the company does, core product/service, customer problem. Second: who the target customer is and why they need this. Third: market positioning, apparent differentiation, go-to-market approach.",
    "sector": "string",
    "business_type": "string",
    "b2b_or_b2c": "string",
    "geography": ["list of strings"],
    "detected_markets": ["list of specific markets, verticals or customer types — minimum 3 entries"],
    "corporate_data": {
      "legal_name": "string or null",
      "company_number": "string or null",
      "jurisdiction": "string or null",
      "company_type": "string or null",
      "status": "string or null",
      "incorporation_date": "string or null",
      "registered_address": "string or null"
    },
    "public_signals": [
      "string — MINIMUM 8 entries. Each must be a specific, concrete, verifiable observation (1-2 sentences). No labels, no metadata — plain text only."
    ],
    "data_source_notes": "string — 2-3 sentence note on data sources available and key gaps"
  }
}
"""


_LANG_OPENERS = {
    "es": "Eres un analista experto en M&A. DEBES responder EXCLUSIVAMENTE en español. Todos los campos de texto en el JSON deben estar en español.",
    "en": "You are an expert M&A analyst. Respond in English.",
    "fr": "Tu es un analyste M&A expert. Tu DOIS répondre EXCLUSIVEMENT en français. Tous les champs texte du JSON doivent être en français.",
    "de": "Du bist ein M&A-Experte. Du MUSST AUSSCHLIESSLICH auf Deutsch antworten. Alle Textfelder im JSON müssen auf Deutsch sein.",
    "it": "Sei un analista M&A esperto. DEVI rispondere ESCLUSIVAMENTE in italiano. Tutti i campi di testo nel JSON devono essere in italiano.",
}


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    return f"""{opener}

You are a senior business analyst specializing in company classification and factual profiling
for investors and M&A analysts doing preliminary screening.

You are writing a professional M&A screening report section that will be used by investors
and acquirers to make real decisions. Your analysis must be exhaustive, well-reasoned and
based on all available evidence. Each section must be substantive — minimum 300 words of
analytical prose. Never truncate your analysis. If you have evidence, analyze it in depth.
If you lack evidence, explain specifically what is missing, why it matters for an acquisition
decision, and what the absence implies about the company.

Your task is to produce a rigorous, evidence-grounded profile of a company based ONLY
on the data provided. You are acting like a careful analyst who has read the company's
website and available registry data, and must now write a clear, honest profile.

Your analysis must be thorough, detailed and professional. Write like a junior M&A analyst
preparing a first screening report. Never summarize when you can analyze. Never use a bullet
point when prose is more informative.

Strict rules:
- Do NOT invent data. If a field cannot be determined from the available sources, set it to null.
- Do NOT copy marketing language verbatim. Translate it into analytical language.
- Separate verified facts (from registry data or explicit website statements) from inferences.
- The "activity" field must be a minimum of 3 full analytical paragraphs describing what the
  company actually does, who it serves, what problem it solves, how it positions itself in the
  market, and what differentiates it from alternatives.
- The "public_signals" list must contain a MINIMUM of 8 and a MAXIMUM of 12 specific, concrete
  observations. Each signal must be a plain text string — do NOT include labels like "evidence_type:" in the string.
- The top-level "evidence_type" field marks the overall classification confidence only.
- If corporate registry data is available, embed it accurately in the factual_profile.
- If a Wikipedia summary is provided, use it as an authoritative reference for factual claims.

LISTING STATUS DETECTION (non-negotiable):

"public" — requires ONE of the following two conditions:

  CONDITION A — one conclusive listed-company signal (sufficient alone):
  · Stock exchange ticker symbol explicitly present (NYSE, NASDAQ, LSE, BME, IBEX 35,
    Euronext, TSX, ASX, HKEX, or any recognisable exchange + ticker format, e.g. "ITX.MC")
  · Explicit phrase: "listed on [exchange]", "cotizada en [bolsa]", "publicly traded",
    "public company", "listed company", "quoted on [exchange]", "bolsa de valores"
  · Securities-regulator filing explicitly cited: SEC 10-K/10-Q/6-K/20-F, CNMV filing,
    FCA prospectus/filing, AMF filing, BaFin notification, or equivalent
  · ISIN code explicitly stated in the source data

  CONDITION B — at least two signals AND at least one must be a listed-market signal:
  Listed-market signals (exist ONLY for exchange-listed companies):
  · Quarterly financial results or half-year results published as regulatory obligation
  · "Información regulada" / "regulated information" / "hechos relevantes" (CNMV)
  · Securities market communications or stock-exchange filings
  · Public share price, stock chart, or live market capitalisation data
  · "Earnings per share", "dividend per share", "scrip dividend" context
  · Wikipedia or credible external source explicitly states exchange listing or ticker
  Any supporting signal (adds weight when combined with a listed-market signal above):
  · Dedicated Investor Relations / "Relaciones con Inversores" section
  · Annual report published for shareholders of the listed entity
  · AGM / Junta General in context of a listed company

  HARD RULE — always "private" or "unknown" when only these are present (NOT sufficient):
  · Investor relations page alone
  · Annual report alone (many private companies publish these)
  · Sustainability or ESG report
  · Press releases or media room
  · Board of directors / shareholder language in general
  · Funding news, VC investment, or IPO plans (≠ already listed)
  · Corporate governance section without listed-market signals
  None of the above, individually or combined, constitutes evidence of stock-exchange listing.

"subsidiary" — explicitly owned by or part of a named parent/holding group:
  · "a [Group] company", "part of [Parent Group]", "wholly owned by", "division of",
    "subsidiary of", or equivalent explicit ownership statement in the source data.

"startup" — explicit growth-stage signals:
  · VC/PE investor names mentioned (Sequoia, a16z, Accel, etc.)
  · "Series A/B/C/D/E funding" explicitly stated; "accelerator"; "incubator"
  · Pre-revenue language; team size <50; founded <10 years with growth-stage framing

"private" — established company, no exchange signals, no VC/startup signals:
  · "privately held", family-owned language, or clear named owner without exchange refs

"unknown" — signals genuinely insufficient or contradictory.

DEFAULT: when uncertain, use "unknown" or "private". Never upgrade to "public" without
at least CONDITION A or CONDITION B above. A false "public" corrupts downstream scoring."""


_LABELS = {
    "es": {
        "header": "EMPRESA A ANALIZAR",
        "registry": "DATOS DEL REGISTRO MERCANTIL (de OpenCorporates — tratar como hechos verificados)",
        "wikipedia": "RESUMEN DE WIKIPEDIA (fuente externa autorizada)",
        "website": "CONTENIDO WEB (texto extraído del sitio web de {name})",
        "instructions": "Basándote estrictamente en los datos anteriores, devuelve un objeto JSON siguiendo este esquema exacto.\nTodos los campos en factual_profile.corporate_data deben provenir de los datos del registro si están disponibles.\nEl campo activity debe tener un mínimo de 3 párrafos analíticos completos.\nLas señales públicas deben ser mínimo 8 entradas específicas y concretas.",
        "schema": "Esquema JSON a seguir:",
        "no_registry": "Sin datos de registro disponibles.",
        "no_website": "No se pudo extraer contenido del sitio web.",
    },
    "en": {
        "header": "COMPANY TO ANALYZE",
        "registry": "CORPORATE REGISTRY DATA (from OpenCorporates — treat as verified facts)",
        "wikipedia": "WIKIPEDIA SUMMARY (authoritative external source)",
        "website": "WEBSITE CONTENT (extracted text from {name}'s website)",
        "instructions": "Based strictly on the data above, return a JSON object matching this exact schema.\nEvery field in factual_profile.corporate_data must come from the registry data if available.\nThe activity field must be a minimum of 3 full analytical paragraphs.\nPublic signals must be minimum 8 specific and concrete entries.",
        "schema": "JSON schema to follow:",
        "no_registry": "No registry data available.",
        "no_website": "No website content could be extracted.",
    },
    "fr": {
        "header": "ENTREPRISE À ANALYSER",
        "registry": "DONNÉES DU REGISTRE DES SOCIÉTÉS (d'OpenCorporates — traiter comme des faits vérifiés)",
        "wikipedia": "RÉSUMÉ WIKIPEDIA (source externe faisant autorité)",
        "website": "CONTENU DU SITE WEB (texte extrait du site de {name})",
        "instructions": "En vous basant strictement sur les données ci-dessus, retournez un objet JSON correspondant à ce schéma exact.\nTous les champs dans factual_profile.corporate_data doivent provenir des données du registre si disponibles.\nLe champ activity doit comporter au minimum 3 paragraphes analytiques complets.\nLes signaux publics doivent être au minimum 8 entrées spécifiques et concrètes.",
        "schema": "Schéma JSON à suivre:",
        "no_registry": "Aucune donnée de registre disponible.",
        "no_website": "Impossible d'extraire le contenu du site web.",
    },
    "de": {
        "header": "ZU ANALYSIERENDE FIRMA",
        "registry": "HANDELSREGISTERDATEN (von OpenCorporates — als verifizierte Fakten behandeln)",
        "wikipedia": "WIKIPEDIA-ZUSAMMENFASSUNG (maßgebliche externe Quelle)",
        "website": "WEBSITE-INHALT (extrahierter Text von der Website von {name})",
        "instructions": "Basierend ausschließlich auf den obigen Daten, gib ein JSON-Objekt zurück, das diesem Schema entspricht.\nAlle Felder in factual_profile.corporate_data müssen aus den Registerdaten stammen, falls verfügbar.\nDas Feld activity muss mindestens 3 vollständige analytische Absätze umfassen.\nÖffentliche Signale müssen mindestens 8 spezifische und konkrete Einträge sein.",
        "schema": "Zu verwendendes JSON-Schema:",
        "no_registry": "Keine Registerdaten verfügbar.",
        "no_website": "Website-Inhalt konnte nicht extrahiert werden.",
    },
    "it": {
        "header": "AZIENDA DA ANALIZZARE",
        "registry": "DATI DEL REGISTRO DELLE IMPRESE (da OpenCorporates — trattare come fatti verificati)",
        "wikipedia": "RIASSUNTO WIKIPEDIA (fonte esterna autorevole)",
        "website": "CONTENUTO DEL SITO WEB (testo estratto dal sito di {name})",
        "instructions": "Basandoti strettamente sui dati sopra, restituisci un oggetto JSON corrispondente a questo schema esatto.\nTutti i campi in factual_profile.corporate_data devono provenire dai dati del registro se disponibili.\nIl campo activity deve avere un minimo di 3 paragrafi analitici completi.\nI segnali pubblici devono essere minimo 8 voci specifiche e concrete.",
        "schema": "Schema JSON da seguire:",
        "no_registry": "Nessun dato di registro disponibile.",
        "no_website": "Impossibile estrarre il contenuto del sito web.",
    },
}


async def run_classifier(
    company_name: str,
    website_url: str,
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    website_text = normalized_data.get("website_text", "")[:12_000]
    corporate = normalized_data.get("corporate_data", {})
    sources_used = normalized_data.get("data_sources_used", [])
    wikipedia = normalized_data.get("wikipedia_summary")
    l = _LABELS.get(language or "es", _LABELS["es"])

    wikipedia_section = ""
    if wikipedia:
        wikipedia_section = f"""
{l['wikipedia']}:
{wikipedia.get('title')}
{wikipedia.get('summary', '')[:2000]}
URL: {wikipedia.get('url')}
---
"""

    user_prompt = f"""
{l['header']}:
{company_name}
URL: {website_url}

{l['registry']}:
{corporate if corporate else l['no_registry']}
{wikipedia_section}
{l['website'].format(name=company_name)}:
---
{website_text if website_text else l['no_website']}
---

{l['instructions']}

{l['schema']}
{_OUTPUT_SCHEMA}
"""

    result = await gemini_client.generate_structured(
        system_prompt=_build_system_prompt(language),
        user_prompt=user_prompt,
        expected_keys=["business_type", "sector", "confidence", "factual_profile"],
        language=language,
    )

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="classifier",
        input_payload={
            "company_name": company_name,
            "website_url": website_url,
            "has_corporate_data": bool(corporate),
            "has_wikipedia": bool(wikipedia),
            "website_chars": len(website_text),
            "language": language,
        },
        output_payload=result["data"],
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return result["data"]
