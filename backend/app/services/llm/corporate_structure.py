"""
LLM Module 9 — Corporate structure and legal signals analysis.
Analyzes legal entity details, subsidiaries, ownership signals,
corporate events, and legally detectable tension signals.
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
  "legal_entity": {
    "name": "string | null",
    "type": "string | null — e.g. Sociedad Anónima, SL, Ltd, GmbH",
    "jurisdiction": "string | null",
    "incorporation_date": "string | null",
    "status": "string | null — active, dissolved, etc.",
    "company_number": "string | null",
    "registered_address": "string | null"
  },
  "subsidiaries": [
    "string — each item 1-2 sentences describing a detected subsidiary or group entity with evidence source."
  ],
  "ownership_signals": "string | null — any public information on shareholders, parent companies, or ownership structure. If none available, state so and explain implications.",
  "corporate_events": [
    {
      "date": "string | null",
      "type": "string — e.g. capital increase, director change, merger, acquisition, dissolution",
      "description": "string — 1-2 sentences describing the event",
      "source": "borme | opencorporates | google_news | gdelt | website",
      "implication": "string — 1-2 sentences on what this event implies for an acquirer."
    }
  ],
  "legal_signals": [
    "string — each item 1-2 sentences on a specific legally relevant signal: litigation, regulatory action, compliance issues. ONLY include if grounded in evidence."
  ],
  "structure_narrative": "REQUIRED: Minimum 200 words synthesizing the corporate structure picture: legal form, jurisdiction, operational footprint, ownership opacity, key events, and what the overall picture means for an acquirer considering deal structuring.",
  "complexity_level": "simple | moderate | complex | unknown",
  "red_flags": [
    "string — specific structural or legal red flags if any, each 1-2 sentences with evidence."
  ],
  "confidence": "high | medium | low",
  "data_limitations": "string | null — what corporate/legal data is absent from public sources and its implications for deal structuring.",
  "acquirability_assessment": {
    "structure_type": "standard_company | holding_group | listed_entity | network_firm | partnership_llp | nonprofit_guarantee | consortium | unknown",
    "group_level_acquirable": true,
    "carveout_relevant": false,
    "acquirability_notes": "REQUIRED: 2-3 sentences on what the legal/organizational structure means for deal feasibility for a typical strategic buyer."
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


_LABELS = {
    "es": {
        "company": "PERFIL DE LA EMPRESA",
        "registry": "DATOS DEL REGISTRO MERCANTIL (OpenCorporates — hechos verificados)",
        "borme": "ENTRADAS DEL BORME (registro mercantil español — actas oficiales)",
        "website": "EXTRACTO DEL SITIO WEB (buscar: estructura de grupo, menciones de entidad legal, referencias a filiales)",
        "gdelt": "NOTICIAS DE GDELT (adquisiciones, fusiones, acciones legales, cambios de propiedad)",
        "google_news": "NOTICIAS DE GOOGLE NEWS (eventos corporativos, actividad M&A, noticias legales)",
        "no_registry": "Sin datos del registro mercantil disponibles.",
        "no_borme": "No se encontraron entradas en BORME.",
        "no_website": "Sin contenido web disponible.",
        "no_gdelt": "No se encontraron artículos de GDELT.",
        "no_google": "No se encontraron artículos de Google News.",
        "instructions": "Analiza la estructura corporativa con rigor.\n- legal_entity: completar SOLO con datos del registro (OpenCorporates, BORME).\n- corporate_events: extraer de entradas BORME y noticias — incluir fecha y fuente.\n- ownership_signals: solo indicar lo que se conoce públicamente.\n- structure_narrative: MÍNIMO 200 palabras sintetizando el panorama completo.\n- Si todos los datos del registro están ausentes, analiza las implicaciones para la estructuración del deal.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "company": "COMPANY PROFILE",
        "registry": "CORPORATE REGISTRY DATA (OpenCorporates — verified facts)",
        "borme": "BORME ENTRIES (Spanish corporate registry — official filings)",
        "website": "WEBSITE EXCERPT (look for group structure, legal entity mentions, subsidiary references)",
        "gdelt": "NEWS FROM GDELT (acquisitions, mergers, legal actions, ownership changes)",
        "google_news": "NEWS FROM GOOGLE NEWS (corporate events, M&A activity, legal news)",
        "no_registry": "No corporate registry data available.",
        "no_borme": "No BORME entries found.",
        "no_website": "No website content available.",
        "no_gdelt": "No GDELT articles found.",
        "no_google": "No Google News articles found.",
        "instructions": "Analyze the corporate structure with rigor.\n- legal_entity: populate ONLY from registry data (OpenCorporates, BORME).\n- corporate_events: extract from BORME entries and news — include date and source.\n- ownership_signals: only state what is publicly known.\n- structure_narrative: MINIMUM 200 words synthesizing the full picture.\n- If all registry data is absent, analyze the implications for deal structuring.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "company": "PROFIL DE L'ENTREPRISE",
        "registry": "DONNÉES DU REGISTRE DES SOCIÉTÉS (OpenCorporates — faits vérifiés)",
        "borme": "ENTRÉES BORME (registre des sociétés espagnol — actes officiels)",
        "website": "EXTRAIT DU SITE WEB (rechercher : structure de groupe, mentions d'entité légale, références aux filiales)",
        "gdelt": "ACTUALITÉS DE GDELT (acquisitions, fusions, actions légales, changements de propriété)",
        "google_news": "ACTUALITÉS DE GOOGLE NEWS (événements d'entreprise, activité M&A, actualités juridiques)",
        "no_registry": "Aucune donnée de registre des sociétés disponible.",
        "no_borme": "Aucune entrée BORME trouvée.",
        "no_website": "Aucun contenu de site web disponible.",
        "no_gdelt": "Aucun article GDELT trouvé.",
        "no_google": "Aucun article Google News trouvé.",
        "instructions": "Analysez la structure d'entreprise avec rigueur.\n- legal_entity : renseigner UNIQUEMENT à partir des données du registre.\n- structure_narrative : MINIMUM 200 mots synthétisant le tableau complet.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "company": "UNTERNEHMENSPROFIL",
        "registry": "HANDELSREGISTERDATEN (OpenCorporates — verifizierte Fakten)",
        "borme": "BORME-EINTRÄGE (spanisches Handelsregister — offizielle Einträge)",
        "website": "WEBSITE-AUSZUG (suche nach: Konzernstruktur, Erwähnungen juristischer Personen, Tochtergesellschaftsreferenzen)",
        "gdelt": "NACHRICHTEN VON GDELT (Akquisitionen, Fusionen, Rechtsschritte, Eigentümerwechsel)",
        "google_news": "NACHRICHTEN VON GOOGLE NEWS (Unternehmensereignisse, M&A-Aktivität, Rechtsnachrichten)",
        "no_registry": "Keine Handelsregisterdaten verfügbar.",
        "no_borme": "Keine BORME-Einträge gefunden.",
        "no_website": "Kein Website-Inhalt verfügbar.",
        "no_gdelt": "Keine GDELT-Artikel gefunden.",
        "no_google": "Keine Google-News-Artikel gefunden.",
        "instructions": "Analysiere die Unternehmensstruktur mit Sorgfalt.\n- legal_entity: NUR aus Registerdaten befüllen.\n- structure_narrative: MINDESTENS 200 Wörter, die das Gesamtbild zusammenfassen.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "company": "PROFILO AZIENDALE",
        "registry": "DATI DEL REGISTRO DELLE IMPRESE (OpenCorporates — fatti verificati)",
        "borme": "VOCI BORME (registro delle imprese spagnolo — atti ufficiali)",
        "website": "ESTRATTO DEL SITO WEB (cerca: struttura di gruppo, menzioni di entità legale, riferimenti a filiali)",
        "gdelt": "NOTIZIE DA GDELT (acquisizioni, fusioni, azioni legali, cambiamenti di proprietà)",
        "google_news": "NOTIZIE DA GOOGLE NEWS (eventi aziendali, attività M&A, notizie legali)",
        "no_registry": "Nessun dato del registro delle imprese disponibile.",
        "no_borme": "Nessuna voce BORME trovata.",
        "no_website": "Nessun contenuto del sito web disponibile.",
        "no_gdelt": "Nessun articolo GDELT trovato.",
        "no_google": "Nessun articolo Google News trovato.",
        "instructions": "Analizza la struttura aziendale con rigore.\n- legal_entity: popolare SOLO dai dati del registro.\n- structure_narrative: MINIMO 200 parole che sintetizzano il quadro completo.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    return f"""{opener}

You are a senior M&A analyst writing the corporate structure and legal signals section
of a company pre-screening report for an investor or acquirer.

You are writing a professional M&A screening report section that will be used by investors
and acquirers to make real decisions. Your analysis must be exhaustive, well-reasoned and
based on all available evidence. Each section must be substantive — minimum 200 words of
analytical prose. Never truncate your analysis. If you have evidence, analyze it in depth.
If you lack evidence, explain specifically what is missing, why it matters for an acquisition
decision, and what the absence implies about the company.

Your analysis must be thorough, detailed and professional. Write like a junior M&A analyst
preparing a first screening report. Never summarize when you can analyze.

Strict rules:
- Work ONLY with registry data (BORME, OpenCorporates) and publicly available signals.
- Every corporate_events item must have a specific source and date if available.
- "structure_narrative" must be minimum 200 words synthesizing the corporate picture.
- "legal_signals" must be grounded in evidence — do NOT include generic legal warnings.
- "ownership_signals": if no public ownership data exists, state so explicitly and explain why
  opacity matters for acquisition structuring.
- "complexity_level" must be justified by the actual data, not assumed.
- If registry data is absent, analyze what this means for an acquirer doing due diligence.

ENTITY TYPE CLASSIFICATION (required — determines acquirability_assessment):
Based on ALL available evidence, classify the entity's structure type:

- "standard_company": regular corporation, limited company, SME, or startup.
  Potentially acquirable as a going concern. group_level_acquirable: true.
- "holding_group": parent holding with subsidiaries. Group-level acquisition is complex;
  individual subsidiaries may be more realistic standalone targets.
- "listed_entity": publicly listed on a stock exchange. Group acquisition requires a
  public-market transaction (takeover/tender offer); only feasible for large buyers.
- "network_firm": NETWORK of legally INDEPENDENT member firms sharing a brand or
  standards (global professional services networks, franchise systems, global alliances).
  THE NETWORK AS A WHOLE IS NOT A SINGLE ACQUIRABLE ENTITY — each member firm is
  separately owned. Set group_level_acquirable=false, carveout_relevant=true.
  Examples: Big Four, second-tier consulting networks, global legal networks.
- "partnership_llp": LLP or partnership — standard equity acquisition blocked by
  partnership structure; buy-out of partners or restructuring required.
  Set group_level_acquirable=false. Common in professional services.
- "nonprofit_guarantee": entity limited by guarantee, foundation, association, or
  charity. Not commercially acquirable. group_level_acquirable=false.
- "consortium": joint venture or multi-party cooperative. Acquisition requires consent
  of all parties; effectively group_level_acquirable=false in most cases.
- "unknown": insufficient data to classify with confidence.

RULES:
- group_level_acquirable MUST be false for: network_firm, partnership_llp,
  nonprofit_guarantee, and consortium.
- carveout_relevant MUST be true when identifiable subsidiaries or independent member
  firms exist that could be acquired separately, even if the group cannot be.
- acquirability_notes must explicitly name the structural barrier if group_level_acquirable
  is false. Do not use vague language — say exactly why group-level M&A is not feasible
  and what alternative acquisition path exists (if any).

EPISTEMIC LANGUAGE RULE — applies to ownership_signals, structure_narrative, legal_signals:
When registry data (OpenCorporates, BORME) is absent or does not confirm a claim, use
appropriately provisional language. Never write ownership, shareholding, or legal status as
established fact when the sole source is the company's own website. Required phrasing:
- "no consta en los registros públicos consultados" — when absent from registries
- "según declara la empresa en su sitio web" — when the source is website only
- "no ha podido verificarse con las fuentes públicas disponibles" — for unverified claims
- "pendiente de verificación en registros oficiales" — for unresolvable uncertainties
Avoid confident formulations like "la empresa pertenece a X" or "la estructura es Y" unless
a specific registry entry or external news source is cited with its origin. When ownership or
legal structure is unknown, state this clearly and explain its implications for deal structuring
without filling the gap with reasonable-sounding inferences.

REGISTRY ABSENCE ≠ ENTITY NON-EXISTENCE (non-negotiable):
When registry data (OpenCorporates, BORME) is absent for a company, this means:
  "the entity was not found in the registry sources consulted by this pipeline"
NOT:
  "the entity does not exist" / "cannot verify legal existence" / "non-acquirable"

Rules when registry data is missing:
1. For private, startup, or established companies with no registry match:
   - Set acquirability_assessment.structure_type = "unknown" UNLESS there is explicit
     affirmative evidence of a non-standard structure (see item 3 below).
   - Do NOT set group_level_acquirable = false based on missing registry data alone.
   - data_limitations MUST say: "legal entity not mapped from sources consulted —
     entity mapping required; standard acquirable legal structure is the reasonable
     default absent evidence to the contrary."
   - Do NOT write: "entity cannot be confirmed", "existence is unverifiable",
     "legal identity cannot be established", or any wording implying non-existence.
2. For established/known companies with strong public footprint but no registry:
   - structure_type = "unknown" or "standard_company" (most likely)
   - acquirability_notes: "legal entity exists but was not mapped from sources consulted;
     entity verification required via direct registry search or legal counsel."
   - group_level_acquirable should be left as true (default) or null (unknown)
     when there is no affirmative structural barrier evidence.
3. Structural barriers (non-acquirable types) REQUIRE explicit affirmative evidence:
   - "network_firm": website or news explicitly states "member firm", "member of network",
     "independently owned member", "franchise network", or similar.
   - "partnership_llp": name ends in LLP, website states "limited liability partnership".
   - "nonprofit_guarantee": registered as charity, foundation, guarantee company.
   - "consortium": explicitly stated as joint venture or consortium of partners.
   Absence of registry data is NEVER sufficient evidence of a structural barrier type.
   Unknown structure = "unknown" structure_type, NOT a barrier type."""


async def run_corporate_structure(
    classification: Dict[str, Any],
    normalized_data: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
) -> Dict[str, Any]:
    corporate = normalized_data.get("corporate_data", {})
    borme = normalized_data.get("borme_entries", [])
    news = normalized_data.get("news_articles", [])
    google_news = normalized_data.get("google_news_articles", [])
    website_text = normalized_data.get("website_text", "")[:4_000]

    import json
    borme_json = json.dumps(borme[:10], ensure_ascii=False, indent=2)
    news_json = json.dumps(news[:5], ensure_ascii=False, indent=2)
    google_news_json = json.dumps(google_news[:5], ensure_ascii=False, indent=2)

    # Pull corporate_data from factual_profile if not directly available
    factual_corp = classification.get("factual_profile", {}).get("corporate_data", {})
    effective_corporate = corporate or factual_corp or {}

    l = _LABELS.get(language or "es", _LABELS["es"])

    # ── Established company detection ──────────────────────────────────────
    # Drives interpretation rules: missing registry ≠ entity non-existence for
    # companies with strong external evidence of existence and operations.
    _evidence_profile = normalized_data.get("evidence_profile") or {}
    _listing_status = (classification.get("listing_status") or "unknown").lower()
    _is_private_or_startup = _listing_status in ("private", "startup")
    _is_established = (
        bool(normalized_data.get("wikipedia_summary"))
        or _evidence_profile.get("is_high_visibility", False)
        or _evidence_profile.get("coverage_tier") in ("rich", "moderate")
        or len(news) + len(google_news) >= 2
        or bool(effective_corporate.get("legal_name"))
    )
    _has_registry = bool(effective_corporate.get("legal_name"))

    user_prompt = f"""
STRUCTURAL ANALYSIS CONTEXT (drives interpretation rules — read before analyzing):
- Established company (Wikipedia / press / coverage tier signals): {'YES — apply REGISTRY ABSENCE ≠ ENTITY NON-EXISTENCE rule' if _is_established else 'NO — standard analysis'}
- Listing status: {_listing_status} (public | private | startup | unknown)
- Private or startup: {'YES — missing registry is expected; do NOT imply non-existence' if _is_private_or_startup else 'NO'}
- Registry data available: {'YES' if _has_registry else 'NO — entity mapping required for known companies; unknown structure_type as default'}
---

{l['company']}:
- Name: {classification.get('factual_profile', {}).get('name', 'unknown')}
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- Geography: {classification.get('geography', [])}

{l['registry']}:
{json.dumps(effective_corporate, ensure_ascii=False, indent=2) if effective_corporate else l['no_registry']}

{l['borme']}:
{borme_json if borme else l['no_borme']}

{l['website']}:
---
{website_text if website_text else l['no_website']}
---

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
        expected_keys=["legal_entity", "structure_narrative", "complexity_level", "confidence", "acquirability_assessment"],
        language=language,
    )

    data = result["data"]

    # ── Post-processing: prevent false-positive non-acquirable classification ──
    # If the LLM set group_level_acquirable=false for a company without any registry
    # data AND without confirmed non-standard structure evidence, that is a false
    # positive caused by the LLM conflating "unknown structure" with a structural barrier.
    _NON_ACQUIRABLE_STRUCT_TYPES = frozenset({
        "network_firm", "partnership_llp", "nonprofit_guarantee", "consortium",
    })
    _acq = data.get("acquirability_assessment") or {}
    _s_type = _acq.get("structure_type", "unknown")
    _g_acq = _acq.get("group_level_acquirable")

    if (
        _g_acq is False
        and _s_type not in _NON_ACQUIRABLE_STRUCT_TYPES
        and not _has_registry
        and not bool(borme)
    ):
        # No registry, no BORME, structure type is not a confirmed barrier —
        # this is entity_mapping_required, not structural non-acquirability.
        _acq["group_level_acquirable"] = None  # unknown, not blocked
        if not _acq.get("acquirability_notes", "").startswith("[CORRECTED]"):
            _acq["acquirability_notes"] = (
                "[CORRECTED: entity mapping required — no registry data available and no "
                "affirmative structural barrier evidence; group_level_acquirable reset from "
                "false to unknown. Standard acquirable structure assumed pending verification.] "
                + (_acq.get("acquirability_notes") or "")
            )
        data["acquirability_assessment"] = _acq
        logger.warning(
            "corporate_structure: false-positive non-acquirable corrected — "
            "struct_type=%s, no registry, no BORME. analysis_id=%s",
            _s_type, analysis_id,
        )

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="corporate_structure",
        input_payload={
            "business_type": classification.get("business_type"),
            "has_corporate_data": bool(effective_corporate),
            "borme_count": len(borme),
            "website_chars": len(website_text),
        },
        output_payload=data,
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return data
