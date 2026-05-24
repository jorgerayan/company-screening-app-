"""
LLM Module 2 — Business model deep analysis.
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
  "model_type": "SaaS | marketplace | agency | ecommerce | B2B services | consultancy | industrial | platform | financial services | other",
  "description": "REQUIRED: 5-7 sentence analytical narrative describing how this business operates commercially.",
  "what_they_sell": "REQUIRED: 2-3 sentence description of the core product or service in analytical terms.",
  "who_they_sell_to": "REQUIRED: 2-3 sentence description of the target customer — size, sector, geography, role.",
  "monetization": "string — primary revenue model label",
  "monetization_detail": "REQUIRED: 3-5 sentence explanation of how the company charges customers.",
  "recurrence": "high | medium | low | unknown",
  "recurrence_analysis": "REQUIRED: 3-5 sentence paragraph assessing revenue recurrence.",
  "scalability": "high | medium | low | unknown",
  "scalability_analysis": "REQUIRED: 3-5 sentence paragraph assessing scalability.",
  "operational_dependency": "REQUIRED: 2-3 sentence description of the key operational constraint.",
  "differentiation": "REQUIRED: 2-3 sentence assessment of differentiation with evidence.",
  "barriers_to_entry": "2-3 sentence assessment of moats, or null if no evidence.",
  "competitive_landscape": "REQUIRED: 3-4 sentence description of the competitive environment.",
  "pricing_signals": "string or null",
  "confidence": "high | medium | low",
  "evidence_type": "verified_fact | reasonable_inference | unverifiable",
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


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    return f"""{opener}

You are a senior M&A analyst writing the business model section of a company pre-screening report.
Your audience is an investor or acquirer who wants to understand how this company makes money,
whether the model is scalable, who the competition is, and what the key vulnerabilities are.

You are writing a professional M&A screening report section that will be used by investors
and acquirers to make real decisions. Your analysis must be exhaustive, well-reasoned and
based on all available evidence. Each section must be substantive — minimum 300 words of
analytical prose. Never truncate your analysis. If you have evidence, analyze it in depth.
If you lack evidence, explain specifically what is missing, why it matters for an acquisition
decision, and what the absence implies about the company.

This section must read like a serious analyst report — substantive, evidence-based, and honest.

Your analysis must be thorough, detailed and professional. Write like a junior M&A analyst
preparing a first screening report. Never summarize when you can analyze. Never use a bullet
point when prose is more informative.

Strict rules:
- Do NOT invent data. Base every assertion on the provided information.
- Do NOT copy marketing language. Translate claims into analytical assessments.
- Where you cannot determine something, say so explicitly and explain why it matters for a buyer.
- The "description" field must be a full analytical narrative of 5-7 sentences minimum.
- The "what_they_sell" field must be 2-3 analytical sentences.
- The "who_they_sell_to" field must be 2-3 sentences covering customer profile in detail.
- Fields marked as "_analysis" must be explanatory paragraphs of MINIMUM 3 sentences each.
- The "competitive_landscape" field must name or describe likely competitors if determinable.
- Pricing signals must quote actual numbers or tiers if visible on the website.

EPISTEMIC LANGUAGE RULE — applies to monetization_detail, recurrence_analysis, scalability_analysis:
When the only available evidence is the company website (no financial filings, no press, no analyst
data, no third-party validation), you MUST use provisional language. Do NOT write as if these are
verified facts. Required phrasing when evidence is limited:
- Use "indicios de…", "probablemente…", "parece que…", "sugiere que…" (or equivalents in language)
- Use "no verificable con evidencia pública disponible", "hipótesis razonable pendiente de validación"
- Set `recurrence` / `scalability` to "unknown" if no external evidence confirms the model type.
- "evidence_type" MUST be "reasonable_inference" if based on website only, "unverifiable" if no
  pricing or operational data is visible at all. Reserve "verified_fact" for externally corroborated
  data points (press, registry, customer reviews, analyst reports).
- Never write "la recurrencia es media" or "la escalabilidad es alta" as if they were hard data
  when the source is only the company's own website."""


_LABELS = {
    "es": {
        "classification": "CONTEXTO DE CLASIFICACIÓN (del paso de análisis anterior)",
        "registry": "DATOS DEL REGISTRO MERCANTIL",
        "website": "CONTENIDO WEB (extraído del sitio web de la empresa)",
        "no_registry": "No disponible.",
        "no_website": "Sin contenido web disponible.",
        "instructions": "Escribe un análisis exhaustivo del modelo de negocio basándote estrictamente en los datos anteriores.\nCada campo '_analysis' debe ser un párrafo analítico real de mínimo 3 frases.\nEl campo description debe tener entre 5-7 frases de prosa analítica genuina.\nDonde los datos sean insuficientes, indícalo y explica específicamente por qué importa para un comprador.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "classification": "CLASSIFICATION CONTEXT (from previous analysis step)",
        "registry": "CORPORATE REGISTRY DATA",
        "website": "WEBSITE CONTENT (extracted from company website)",
        "no_registry": "Not available.",
        "no_website": "No website content available.",
        "instructions": "Write a thorough business model analysis based strictly on the data above.\nEvery '_analysis' field must be a real analytical paragraph of minimum 3 sentences.\nThe description field must be 5-7 sentences of genuine analytical prose.\nWhere data is insufficient, say so and explain specifically why it matters for a buyer.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "classification": "CONTEXTE DE CLASSIFICATION (de l'étape d'analyse précédente)",
        "registry": "DONNÉES DU REGISTRE DES SOCIÉTÉS",
        "website": "CONTENU DU SITE WEB (extrait du site de l'entreprise)",
        "no_registry": "Non disponible.",
        "no_website": "Aucun contenu de site web disponible.",
        "instructions": "Rédigez une analyse approfondie du modèle d'affaires en vous basant strictement sur les données ci-dessus.\nChaque champ '_analysis' doit être un vrai paragraphe analytique d'au moins 3 phrases.\nLe champ description doit comporter 5-7 phrases de prose analytique authentique.\nLorsque les données sont insuffisantes, indiquez-le et expliquez pourquoi c'est important pour un acheteur.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "classification": "KLASSIFIZIERUNGSKONTEXT (aus dem vorherigen Analyseschritt)",
        "registry": "HANDELSREGISTERDATEN",
        "website": "WEBSITE-INHALT (von der Unternehmenswebsite extrahiert)",
        "no_registry": "Nicht verfügbar.",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "instructions": "Schreibe eine gründliche Geschäftsmodellanalyse streng auf der Grundlage der obigen Daten.\nJedes '_analysis'-Feld muss ein echter analytischer Absatz mit mindestens 3 Sätzen sein.\nDas Beschreibungsfeld muss 5-7 Sätze echter analytischer Prosa enthalten.\nWo Daten unzureichend sind, gib dies an und erkläre, warum es für einen Käufer wichtig ist.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "classification": "CONTESTO DI CLASSIFICAZIONE (dal passaggio di analisi precedente)",
        "registry": "DATI DEL REGISTRO DELLE IMPRESE",
        "website": "CONTENUTO DEL SITO WEB (estratto dal sito dell'azienda)",
        "no_registry": "Non disponibile.",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "instructions": "Scrivi un'analisi approfondita del modello di business basandoti strettamente sui dati sopra.\nOgni campo '_analysis' deve essere un vero paragrafo analitico di almeno 3 frasi.\nIl campo description deve avere 5-7 frasi di prosa analitica genuina.\nDove i dati sono insufficienti, indicalo e spiega perché è importante per un acquirente.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


async def run_business_model(
    classification: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    website_text = normalized_data.get("website_text", "")[:10_000]
    corporate = normalized_data.get("corporate_data", {})
    l = _LABELS.get(language or "es", _LABELS["es"])

    user_prompt = f"""
{l['classification']}:
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- B2B/B2C: {classification.get('b2b_or_b2c', 'unknown')}
- Main product/service: {classification.get('main_product_or_service', 'unknown')}
- Value proposition: {classification.get('value_proposition_summary', 'unknown')}
- Geography: {classification.get('geography', [])}
- Classification confidence: {classification.get('confidence', 'unknown')}

{l['registry']}:
{corporate if corporate else l['no_registry']}

{l['website']}:
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
        expected_keys=["model_type", "description", "monetization", "recurrence_analysis", "scalability_analysis"],
        language=language,
    )

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="business_model",
        input_payload={
            "business_type": classification.get("business_type"),
            "sector": classification.get("sector"),
            "website_chars": len(website_text),
        },
        output_payload=result["data"],
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return result["data"]
