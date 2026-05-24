"""
LLM Module 8 — Operational signals and business health.
Analyzes hiring patterns, product launches, geographic expansion,
employer reputation, and tension signals detectable from public data.
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
  "hiring_signals": {
    "detected": true,
    "volume": "high | moderate | low | none | unknown",
    "role_types": "string | null — what types of roles are being hired: technical, sales, ops, etc.",
    "interpretation": "REQUIRED: 2-3 sentences on what the hiring pattern implies about company trajectory."
  },
  "product_launches": [
    "string — each item 1-2 sentences describing a detected product or service launch with date if known."
  ],
  "geographic_expansion": "string | null — detected expansion into new markets or regions, with evidence.",
  "employer_reputation": {
    "glassdoor_rating": null,
    "review_count": null,
    "would_recommend_pct": null,
    "ceo_approval_pct": null,
    "summary": "REQUIRED: 2-3 sentences interpreting the employer reputation picture — use Glassdoor data if available, otherwise assess from other signals.",
    "red_flags": [
      "string — specific employer reputation concerns if any."
    ]
  },
  "tension_signals": [
    "string — each item 1-2 sentences on a specific tension signal (litigation, layoffs, executive departure, regulatory issue) with source."
  ],
  "operational_narrative": "REQUIRED: Minimum 300 words. Synthesis of all operational signals: hiring trajectory, product momentum, geographic footprint, employer health, and any signs of operational stress. Be honest and evidence-based.",
  "overall_health": "strong | stable | mixed_signals | concerning | unknown",
  "confidence": "high | medium | low",
  "data_limitations": "string | null — what operational data is absent from public sources and why it matters for acquisition due diligence."
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
        "website": "CONTENIDO WEB (buscar: secciones de empleo/trabajo, lanzamientos de productos, anuncios de expansión)",
        "glassdoor": "DATOS DE GLASSDOOR (reputación como empleador)",
        "borme": "REGISTRO MERCANTIL — BORME (eventos operativos, cambios de capital, actas legales)",
        "gdelt": "NOTICIAS DE GDELT (eventos operativos, lanzamientos, litigios, despidos)",
        "google_news": "NOTICIAS DE GOOGLE NEWS (señales operativas, noticias de producto, noticias de empleador)",
        "glassdoor_structured": "DATOS ESTRUCTURADOS DE GLASSDOOR (para campos de employer_reputation)",
        "no_website": "Sin contenido web disponible.",
        "no_borme": "No se encontraron entradas en BORME.",
        "no_gdelt": "No se encontraron artículos de GDELT.",
        "no_google": "No se encontraron artículos de Google News.",
        "no_glassdoor": "Sin datos de Glassdoor disponibles — establecer glassdoor_rating, review_count, would_recommend_pct, ceo_approval_pct a null.",
        "instructions": "Analiza todas las señales operativas con rigor. No inventes señales.\noperational_narrative: MÍNIMO 300 palabras.\nhiring_signals, tension_signals: deben estar fundamentados en los datos anteriores.\nPara employer_reputation: rellena los campos de Glassdoor con los datos estructurados anteriores si están disponibles.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "company": "COMPANY PROFILE",
        "website": "WEBSITE CONTENT (look for: careers/jobs sections, product launches, expansion announcements)",
        "glassdoor": "GLASSDOOR EMPLOYER DATA",
        "borme": "CORPORATE REGISTRY — BORME (operational events, capital changes, legal entries)",
        "gdelt": "NEWS FROM GDELT (operational events, launches, litigation, layoffs)",
        "google_news": "NEWS FROM GOOGLE NEWS (operational signals, product news, employer news)",
        "glassdoor_structured": "GLASSDOOR STRUCTURED DATA (for employer_reputation fields)",
        "no_website": "No website content available.",
        "no_borme": "No BORME entries found.",
        "no_gdelt": "No GDELT articles found.",
        "no_google": "No Google News articles found.",
        "no_glassdoor": "No Glassdoor data available — set glassdoor_rating, review_count, would_recommend_pct, ceo_approval_pct to null.",
        "instructions": "Analyze all operational signals rigorously. Do not invent signals.\noperational_narrative: MINIMUM 300 words.\nhiring_signals, tension_signals: must be grounded in the data above.\nFor employer_reputation: populate glassdoor fields from structured data above if available.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "company": "PROFIL DE L'ENTREPRISE",
        "website": "CONTENU DU SITE WEB (rechercher : sections emploi/offres, lancements de produits, annonces d'expansion)",
        "glassdoor": "DONNÉES GLASSDOOR (réputation employeur)",
        "borme": "REGISTRE DES SOCIÉTÉS — BORME (événements opérationnels, changements de capital, actes légaux)",
        "gdelt": "ACTUALITÉS DE GDELT (événements opérationnels, lancements, litiges, licenciements)",
        "google_news": "ACTUALITÉS DE GOOGLE NEWS (signaux opérationnels, actualités produits, actualités employeur)",
        "glassdoor_structured": "DONNÉES STRUCTURÉES GLASSDOOR (pour les champs employer_reputation)",
        "no_website": "Aucun contenu de site web disponible.",
        "no_borme": "Aucune entrée BORME trouvée.",
        "no_gdelt": "Aucun article GDELT trouvé.",
        "no_google": "Aucun article Google News trouvé.",
        "no_glassdoor": "Aucune donnée Glassdoor disponible — définir glassdoor_rating, review_count, would_recommend_pct, ceo_approval_pct à null.",
        "instructions": "Analysez tous les signaux opérationnels avec rigueur. N'inventez pas de signaux.\noperational_narrative : MINIMUM 300 mots.\nhiring_signals, tension_signals : doivent être fondés sur les données ci-dessus.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "company": "UNTERNEHMENSPROFIL",
        "website": "WEBSITE-INHALT (suche nach: Karriere/Jobs-Bereichen, Produktlaunches, Expansionsankündigungen)",
        "glassdoor": "GLASSDOOR-ARBEITGEBERDATEN",
        "borme": "HANDELSREGISTER — BORME (operative Ereignisse, Kapitaländerungen, rechtliche Einträge)",
        "gdelt": "NACHRICHTEN VON GDELT (operative Ereignisse, Launches, Rechtsstreitigkeiten, Entlassungen)",
        "google_news": "NACHRICHTEN VON GOOGLE NEWS (operative Signale, Produktnachrichten, Arbeitgebernachrichten)",
        "glassdoor_structured": "GLASSDOOR STRUKTURIERTE DATEN (für employer_reputation-Felder)",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "no_borme": "Keine BORME-Einträge gefunden.",
        "no_gdelt": "Keine GDELT-Artikel gefunden.",
        "no_google": "Keine Google-News-Artikel gefunden.",
        "no_glassdoor": "Keine Glassdoor-Daten verfügbar — glassdoor_rating, review_count, would_recommend_pct, ceo_approval_pct auf null setzen.",
        "instructions": "Analysiere alle operativen Signale sorgfältig. Erfinde keine Signale.\noperational_narrative: MINDESTENS 300 Wörter.\nhiring_signals, tension_signals: müssen in den obigen Daten begründet sein.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "company": "PROFILO AZIENDALE",
        "website": "CONTENUTO DEL SITO WEB (cerca: sezioni carriere/lavoro, lanci di prodotti, annunci di espansione)",
        "glassdoor": "DATI GLASSDOOR (reputazione datore di lavoro)",
        "borme": "REGISTRO DELLE IMPRESE — BORME (eventi operativi, variazioni di capitale, atti legali)",
        "gdelt": "NOTIZIE DA GDELT (eventi operativi, lanci, contenziosi, licenziamenti)",
        "google_news": "NOTIZIE DA GOOGLE NEWS (segnali operativi, notizie di prodotto, notizie datore di lavoro)",
        "glassdoor_structured": "DATI STRUTTURATI GLASSDOOR (per i campi employer_reputation)",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "no_borme": "Nessuna voce BORME trovata.",
        "no_gdelt": "Nessun articolo GDELT trovato.",
        "no_google": "Nessun articolo Google News trovato.",
        "no_glassdoor": "Nessun dato Glassdoor disponibile — impostare glassdoor_rating, review_count, would_recommend_pct, ceo_approval_pct a null.",
        "instructions": "Analizza tutti i segnali operativi con rigore. Non inventare segnali.\noperational_narrative: MINIMO 300 parole.\nhiring_signals, tension_signals: devono essere fondati sui dati sopra.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    return f"""{opener}

You are a senior M&A analyst writing the operational signals section of a company
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
- Work ONLY with the data provided. Do NOT invent job postings, product launches, or events.
- The "operational_narrative" field must be minimum 300 words.
- "hiring_signals": infer from website careers page content, job board mentions in news, or
  any reference to hiring/headcount in articles. If none found, state so clearly.
- "tension_signals": look for litigation mentions, executive departures, layoff news,
  regulatory actions, or any negative operational indicators in news and website.
- "overall_health" must be evidence-based — do not default to "unknown" if signals exist.
- Glassdoor data if available is a primary source for employer reputation — use it directly.
- If data is sparse, analyze thoroughly what its absence implies for an acquirer."""


async def run_operational_signals(
    classification: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    website_text = normalized_data.get("website_text", "")[:8_000]
    news = normalized_data.get("news_articles", [])
    google_news = normalized_data.get("google_news_articles", [])
    borme = normalized_data.get("borme_entries", [])
    glassdoor = normalized_data.get("glassdoor_data")

    import json
    news_json = json.dumps(news[:8], ensure_ascii=False, indent=2)
    google_news_json = json.dumps(google_news[:8], ensure_ascii=False, indent=2)
    borme_json = json.dumps(borme[:5], ensure_ascii=False, indent=2)

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

    glassdoor_fields = {}
    if glassdoor:
        glassdoor_fields = {
            "glassdoor_rating": glassdoor.get("overall_rating"),
            "review_count": glassdoor.get("review_count"),
            "would_recommend_pct": glassdoor.get("recommend_pct"),
            "ceo_approval_pct": glassdoor.get("ceo_approval_pct"),
        }

    user_prompt = f"""
{l['company']}:
- Name: {classification.get('factual_profile', {}).get('name', 'unknown')}
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- Geography: {classification.get('geography', [])}

{l['website']}:
---
{website_text if website_text else l['no_website']}
---
{glassdoor_section}
{l['borme']}:
{borme_json if borme else l['no_borme']}

{l['gdelt']}:
{news_json if news else l['no_gdelt']}

{l['google_news']}:
{google_news_json if google_news else l['no_google']}

{l['glassdoor_structured']}:
{json.dumps(glassdoor_fields, ensure_ascii=False) if glassdoor_fields else l['no_glassdoor']}

{l['instructions']}

{l['schema']}
{_OUTPUT_SCHEMA}
"""

    result = await gemini_client.generate_structured(
        system_prompt=_build_system_prompt(language),
        user_prompt=user_prompt,
        expected_keys=["hiring_signals", "operational_narrative", "overall_health", "confidence"],
        language=language,
    )

    data = result["data"]

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="operational_signals",
        input_payload={
            "business_type": classification.get("business_type"),
            "sector": classification.get("sector"),
            "website_chars": len(website_text),
            "news_count": len(news),
            "borme_count": len(borme),
            "has_glassdoor": bool(glassdoor),
        },
        output_payload=data,
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return data
