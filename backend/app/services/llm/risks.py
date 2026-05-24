"""
LLM Module 4 — Risk identification and analysis.
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
  "risks": [
    {
      "name": "short risk label — 3-6 words, specific",
      "severity": "high | medium | low",
      "risk_category": "market | competition | opacity | differentiation | commercial_dependency | operational | regulatory | financial_visibility | product_concentration | team_dependency | scalability | other",
      "evidence": "REQUIRED: 2-3 sentences on the specific data point or absence that grounds this risk.",
      "explanation": "REQUIRED: Minimum 5 sentences. Cover: what the risk is, why it matters, potential impact, model vs company specific, why it deserves attention.",
      "what_to_validate": "REQUIRED: 2-3 concrete, specific, actionable validation steps.",
      "evidence_type": "verified_fact | reasonable_inference | unverifiable"
    }
  ],
  "risk_narrative": "REQUIRED: Minimum 4 sentences synthesizing the overall risk picture.",
  "risk_summary": "1-2 sentence headline summary of the risk picture.",
  "confidence": "high | medium | low",
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

You are a risk analyst writing the risk section of a company pre-screening report
for a potential investor or acquirer.

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
- Identify MINIMUM 6 risks, maximum 8. All must be grounded in this specific company's data.
- Do NOT list generic risks. Every risk must reference something specific about THIS company.
- The "explanation" field must be minimum 5 sentences covering: what the risk is, why it matters,
  potential impact, whether it's model-specific or company-specific, why it deserves attention.
- The "what_to_validate" field must contain 2-3 concrete, specific, actionable validation steps.
- If public data is sparse, include AT MOST ONE consolidated "limited financial disclosure"
  risk rated MEDIUM for private/startup/SME companies (see PRE-SCREENING CONTEXT below).
- The risk_narrative must be minimum 4 sentences.

PRE-SCREENING CONTEXT — FINANCIAL DATA ABSENCE (non-negotiable):
This analysis is based exclusively on public sources. This is a pre-screening report, not a
full due diligence exercise. For private companies, startups, SMEs, founder-owned businesses,
and subsidiaries, the following data is typically absent from public sources. This absence is
NORMAL and EXPECTED — it is NOT a red flag, NOT critical opacity, NOT a valuation blocker:
  ARR / MRR / EBITDA / gross margin / net margin / churn / LTV / CAC / NRR
  Cap table / ownership structure / investor names (unless publicly announced)
  Audited financial statements / internal management accounts
  Customer concentration details / named customer lists
  Detailed unit economics at operating level

DISCLOSURE LIMITATION SEVERITY RULES (non-negotiable):
0. PUBLIC COMPANY RULE (highest priority — overrides everything below):
   If the COMPANY PROFILE shows listing_status = "public":
   DO NOT include any entry in the "risks" array related to financial data absence.
   Public companies are legally required to file periodic financial disclosures.
   Absent financial data in the extracted payload = pipeline/scraping limitation only.
   If financial data was not retrieved, record it ONLY in the "notes" field, using
   language such as: "Financial data not extracted from public sources — pipeline
   limitation. Mandatory periodic disclosures exist but were not retrieved by the
   current scraping pass." This note must NOT appear in "risks" or "risk_narrative".
   FORBIDDEN anywhere in risks/risk_narrative for public companies:
   "limited financial visibility", "lack of financial data", "financial opacity",
   "limited disclosure", "missing ARR/EBITDA/margins", or any risk whose evidence
   field cites absent financial metrics.
   All 6–8 risks MUST be substantive business risks: competitive dynamics, regulation,
   operational execution, market saturation, technology, customer concentration (if
   evidenced), litigation (if evidenced), key-person risk, geopolitical exposure, etc.
1. CONSOLIDATION: Do NOT generate multiple separate risks for the same root cause.
   WRONG: separate risks for "No ARR", "No EBITDA", "No churn", "No audited financials"
   CORRECT: ONE single consolidated risk — e.g. "Limited public financial disclosure —
   validation required in due diligence"
2. DEFAULT SEVERITY for private/startup/SME with coherent external signals and no
   contradictory evidence: severity = "medium". Never "high" by default for mere absence.
3. UPGRADE to severity = "high" ONLY when at least ONE of these explicit negative signals
   is present and attributable to this specific company:
   - Explicit contradictory metrics (claimed scale vs detectable external footprint)
   - Fraud allegations, regulatory sanctions, or administrative penalties
   - Insolvency proceedings, bankruptcy, or creditor enforcement actions
   - Material confirmed customer loss (verifiable, not inferred)
   - Severe confirmed layoffs or operational distress
   - Public company failing to file mandatory disclosures it is legally required to make
   - Self-reported claims central to the investment thesis that are materially implausible
     given all other available evidence
4. FORBIDDEN language when the only issue is normal private-company non-disclosure:
   "critical opacity" / "severe lack of transparency" / "impossible to value" /
   "valuation cannot proceed" / "major red flag" / "critical informational gap" /
   "total lack of financial visibility"
   Use instead: "financial performance not publicly verifiable" /
   "requires validation in due diligence" / "unit economics should be confirmed with
   internal data" / "public sources do not allow margin or retention analysis" /
   "valuation would require access to internal financials"
5. The remaining 5–7 risks MUST be substantive, independent, and company-specific:
   competitive dynamics, regulatory pressure, technology defensibility, customer
   concentration (if evidenced), key-person / retention risk, execution risk, market
   saturation, operational dependency, leverage / debt, litigation (if evidenced).
   Do NOT fill the risk list with disclosure sub-items disguised as independent risks."""


_LABELS = {
    "es": {
        "profile": "PERFIL DE LA EMPRESA",
        "biz_model": "ANÁLISIS DEL MODELO DE NEGOCIO",
        "traction": "EVALUACIÓN DE TRACCIÓN",
        "website": "EXTRACTO DEL SITIO WEB",
        "glassdoor": "DATOS DE GLASSDOOR (reputación como empleador)",
        "similarweb": "DATOS DE TRÁFICO WEB (SimilarWeb)",
        "no_website": "Sin contenido web disponible.",
        "instructions": "Identifica entre 6 y 8 riesgos específicos y materiales fundamentados en los datos de esta empresa.\nCampo explanation: mínimo 5 frases. what_to_validate: concreto y accionable.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "profile": "COMPANY PROFILE",
        "biz_model": "BUSINESS MODEL ANALYSIS",
        "traction": "TRACTION ASSESSMENT",
        "website": "WEBSITE EXCERPT",
        "glassdoor": "GLASSDOOR EMPLOYER DATA",
        "similarweb": "SIMILARWEB WEB TRAFFIC DATA",
        "no_website": "No website content available.",
        "instructions": "Identify between 6 and 8 specific, material risks grounded in this company's data.\nexplanation field: minimum 5 sentences. what_to_validate: concrete and actionable.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "profile": "PROFIL DE L'ENTREPRISE",
        "biz_model": "ANALYSE DU MODÈLE D'AFFAIRES",
        "traction": "ÉVALUATION DE LA TRACTION",
        "website": "EXTRAIT DU SITE WEB",
        "glassdoor": "DONNÉES GLASSDOOR (réputation employeur)",
        "similarweb": "DONNÉES DE TRAFIC WEB (SimilarWeb)",
        "no_website": "Aucun contenu de site web disponible.",
        "instructions": "Identifiez entre 6 et 8 risques spécifiques et matériels fondés sur les données de cette entreprise.\nChamp explanation : minimum 5 phrases. what_to_validate : concret et actionnable.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "profile": "UNTERNEHMENSPROFIL",
        "biz_model": "GESCHÄFTSMODELLANALYSE",
        "traction": "TRAKTIONSBEWERTUNG",
        "website": "WEBSITE-AUSZUG",
        "glassdoor": "GLASSDOOR-ARBEITGEBERDATEN",
        "similarweb": "WEB-TRAFFIC-DATEN (SimilarWeb)",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "instructions": "Identifiziere zwischen 6 und 8 spezifische, wesentliche Risiken, die in den Daten dieses Unternehmens begründet sind.\nFeld explanation: mindestens 5 Sätze. what_to_validate: konkret und umsetzbar.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "profile": "PROFILO AZIENDALE",
        "biz_model": "ANALISI DEL MODELLO DI BUSINESS",
        "traction": "VALUTAZIONE DELLA TRAZIONE",
        "website": "ESTRATTO DEL SITO WEB",
        "glassdoor": "DATI GLASSDOOR (reputazione datore di lavoro)",
        "similarweb": "DATI TRAFFICO WEB (SimilarWeb)",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "instructions": "Identifica tra 6 e 8 rischi specifici e materiali fondati sui dati di questa azienda.\nCampo explanation: minimo 5 frasi. what_to_validate: concreto e attuabile.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


async def run_risks(
    classification: Dict[str, Any],
    business_model: Dict[str, Any],
    traction: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    signals = traction.get("signals", [])
    website_snippet = normalized_data.get("website_text", "")[:5_000]
    glassdoor = normalized_data.get("glassdoor_data")
    similarweb = normalized_data.get("similarweb_data")
    l = _LABELS.get(language or "es", _LABELS["es"])

    glassdoor_section = ""
    if glassdoor:
        glassdoor_section = f"""
{l['glassdoor']}:
- Overall rating: {glassdoor.get('overall_rating', 'N/A')} / 5
- Number of reviews: {glassdoor.get('review_count', 'N/A')}
- Would recommend: {glassdoor.get('recommend_pct', 'N/A')}%
- CEO approval: {glassdoor.get('ceo_approval_pct', 'N/A')}%
"""

    similarweb_section = ""
    if similarweb:
        similarweb_section = f"""
{l['similarweb']}:
- Global rank: #{similarweb.get('global_rank', 'unknown')}
- Monthly visits estimate: {similarweb.get('monthly_visits_estimate', 'unknown')}
- Category: {similarweb.get('category', 'unknown')}
"""

    _listing_status = (classification.get("listing_status") or "unknown").lower()
    _is_private_or_startup = _listing_status in ("private", "startup", "subsidiary")
    _disclosure_context = (
        "PRIVATE/STARTUP — missing financial data is EXPECTED; "
        "apply PRE-SCREENING CONTEXT rules; disclosure limitation = MEDIUM by default"
        if _is_private_or_startup
        else (
            "PUBLIC COMPANY — missing financial data = pipeline/scraping limitation ONLY; "
            "DO NOT generate any financial disclosure risk; public companies file mandatory "
            "disclosures; absent data here = not retrieved, not absent in reality"
            if _listing_status == "public"
            else "LISTING STATUS UNKNOWN — apply cautious inference; absence reduces confidence only"
        )
    )

    user_prompt = f"""
{l['profile']}:
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- B2B/B2C: {classification.get('b2b_or_b2c', 'unknown')}
- Listing status: {_listing_status} — {_disclosure_context}
- Geography: {classification.get('geography', [])}
- Main product/service: {classification.get('main_product_or_service', 'unknown')}

{l['biz_model']}:
- Model type: {business_model.get('model_type', 'unknown')}
- Monetization: {business_model.get('monetization', 'unknown')}
- Monetization detail: {business_model.get('monetization_detail', 'unknown')}
- Recurrence: {business_model.get('recurrence', 'unknown')} — {business_model.get('recurrence_analysis', '')}
- Scalability: {business_model.get('scalability', 'unknown')} — {business_model.get('scalability_analysis', '')}
- Operational dependency: {business_model.get('operational_dependency', 'unknown')}
- Differentiation: {business_model.get('differentiation', 'none apparent')}
- Barriers to entry: {business_model.get('barriers_to_entry', 'none apparent')}
- Competitive landscape: {business_model.get('competitive_landscape', 'unknown')}
- Business model confidence: {business_model.get('confidence', 'unknown')}
- Business model notes: {business_model.get('notes', 'none')}

{l['traction']}:
- Data availability: {traction.get('data_availability', 'unknown')}
- Number of external signals found: {len(signals)}
- Growth narrative: {traction.get('growth_narrative', 'unknown')}
- Internal vs external consistency: {traction.get('internal_vs_external_consistency', 'unknown')}
- Data gaps: {traction.get('data_gaps', 'unknown')}

{l['website']}:
---
{website_snippet if website_snippet else l['no_website']}
---
{glassdoor_section}{similarweb_section}
{l['instructions']}

{l['schema']}
{_OUTPUT_SCHEMA}
"""

    result = await gemini_client.generate_structured(
        system_prompt=_build_system_prompt(language),
        user_prompt=user_prompt,
        expected_keys=["risks", "risk_narrative", "risk_summary", "confidence"],
        language=language,
    )

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="risks",
        input_payload={
            "business_type": classification.get("business_type"),
            "model_type": business_model.get("model_type"),
            "traction_data_availability": traction.get("data_availability"),
            "signal_count": len(signals),
        },
        output_payload=result["data"],
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return result["data"]
