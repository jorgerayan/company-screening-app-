"""
LLM Module 5 — Conclusion, composite scoring, and prioritization.

Scoring scale:
  9.0 - 10.0 → "Oportunidad excepcional"  → priority_rating: high
  7.5 -  8.9 → "Alta prioridad"            → priority_rating: high
  6.0 -  7.4 → "Interesante con potencial" → priority_rating: interesting_with_doubts
  4.5 -  5.9 → "Interesante con dudas"     → priority_rating: interesting_with_doubts
  3.0 -  4.4 → "Baja prioridad"            → priority_rating: low
  1.0 -  2.9 → "No recomendado"            → priority_rating: low
  0.0        → "Información insuficiente"  → priority_rating: insufficient_data
"""
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.gemini_client import gemini_client
from app.models.llm_result import LLMResult
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_OUTPUT_SCHEMA = """
{
  "overall_score": 7.4,
  "overall_label": "Alta prioridad | Interesante con potencial | Interesante con dudas | Baja prioridad | No recomendado | Oportunidad excepcional | Información insuficiente | Activo atractivo sujeto a verificación | Estructura no adquirible como grupo — analizar activos o filiales",
  "score_rationale": "REQUIRED: 3-4 sentences explaining why this specific overall score was assigned, referencing the most decisive evidence and which scoring caps were applied.",
  "dimension_scores": {
    "business_model": {
      "score": 8.0,
      "rationale": "REQUIRED: 2-3 sentences explaining this dimension score with specific evidence.",
      "evidence_quality": "sufficient | limited | insufficient"
    },
    "traction_and_growth": {
      "score": 6.5,
      "rationale": "REQUIRED: 2-3 sentences explaining this dimension score with specific evidence.",
      "evidence_quality": "sufficient | limited | insufficient"
    },
    "risk_profile": {
      "score": 7.0,
      "rationale": "REQUIRED: 2-3 sentences explaining this dimension score with specific evidence.",
      "evidence_quality": "sufficient | limited | insufficient"
    },
    "management_and_team": {
      "score": 6.0,
      "rationale": "REQUIRED: 2-3 sentences explaining this dimension score with specific evidence.",
      "evidence_quality": "sufficient | limited | insufficient"
    },
    "competitive_position": {
      "score": 8.5,
      "rationale": "REQUIRED: 2-3 sentences explaining this dimension score with specific evidence.",
      "evidence_quality": "sufficient | limited | insufficient"
    },
    "acquirability": {
      "score": 7.0,
      "rationale": "REQUIRED: 2-3 sentences explaining the acquirability score — ownership structure, size, blockers, or why this is/isn't a realistic acquisition target.",
      "evidence_quality": "sufficient | limited | insufficient"
    }
  },
  "priority_rating": "high | interesting_with_doubts | low | insufficient_data",
  "summary": "REQUIRED: 150-250 words of specific, evidence-grounded prose. Conclude with a sentence on overall readiness for M&A evaluation.",
  "investment_thesis": "REQUIRED: 3-4 sentences on the potential upside case for the right buyer. If evidence is insufficient, state what would need to be confirmed first.",
  "key_strengths": [
    "string — MINIMUM 3 items. Each 2-3 sentences with specific evidence."
  ],
  "key_concerns": [
    "string — MINIMUM 3 items. Each 2-3 sentences explaining specifically why it matters."
  ],
  "key_questions": [
    "string — MINIMUM 5 items. Each specific and answerable."
  ],
  "next_steps": [
    "string — MINIMUM 3 items. Each concrete, specific, actionable."
  ],
  "readiness": {
    "financial_data": "high | medium | low",
    "legal_entity": "high | medium | low",
    "management_visibility": "high | medium | low",
    "market_validation": "high | medium | low",
    "overall": "high | medium | low",
    "notes": "2-3 sentences on what gaps prevent a full M&A evaluation and what would resolve them."
  },
  "confidence": "high | medium | low",
  "data_limitations": "2-3 sentence description of key data gaps, or null if data was sufficient"
}
"""


def _infer_entity_detection_status(
    struct_type: str,
    group_acquirable,       # bool | None
    has_legal_data: bool,
    listing_status: str,
    is_established: bool,
    has_any_external: bool,
) -> str:
    """
    Distinguish structurally non-acquirable entities from those that merely need
    legal-entity mapping. Prevents absence of public registry data from being
    misread as a structural acquisition barrier.

    Returns:
      "structurally_non_acquirable" — confirmed structural barrier (network/LLP/non-profit/consortium)
      "verified_entity"             — registry or legal data confirmed in public sources
      "entity_mapping_required"     — company exists but legal entity not extracted publicly
      "unknown"                     — insufficient signals to determine either way
    """
    _NON_ACQUIRABLE = frozenset({"network_firm", "partnership_llp", "nonprofit_guarantee", "consortium"})
    if group_acquirable is False and struct_type in _NON_ACQUIRABLE:
        return "structurally_non_acquirable"
    if has_legal_data:
        return "verified_entity"
    # Private/startup companies almost certainly have a legal entity —
    # it just was not extracted. Same for established companies with external coverage.
    if listing_status in ("private", "startup", "subsidiary") or is_established or has_any_external:
        return "entity_mapping_required"
    return "unknown"


def _score_to_priority_rating(score: float) -> str:
    """Derive priority_rating from overall_score as a validation fallback.

    Mapping matches the documented scoring scale:
      9.0-10.0 → high            (Oportunidad excepcional)
      7.5-8.9  → high            (Alta prioridad)
      4.5-7.4  → interesting_with_doubts  (Interesante con potencial / dudas)
      1.0-4.4  → low             (Baja prioridad / No recomendado)
      0.0      → insufficient_data
    """
    if score == 0.0:
        return "insufficient_data"
    elif score >= 7.5:
        return "high"
    elif score >= 4.5:
        return "interesting_with_doubts"
    else:
        return "low"


_LANG_OPENERS = {
    "es": "Eres un analista experto en M&A. DEBES responder EXCLUSIVAMENTE en español. Todos los campos de texto en el JSON deben estar en español.",
    "en": "You are an expert M&A analyst. Respond in English.",
    "fr": "Tu es un analyste M&A expert. Tu DOIS répondre EXCLUSIVEMENT en français. Tous les champs texte du JSON doivent être en français.",
    "de": "Du bist ein M&A-Experte. Du MUSST AUSSCHLIESSLICH auf Deutsch antworten. Alle Textfelder im JSON müssen auf Deutsch sein.",
    "it": "Sei un analista M&A esperto. DEVI rispondere ESCLUSIVAMENTE in italiano. Tutti i campi di testo nel JSON devono essere in italiano.",
}


_LABELS = {
    "es": {
        "header": "RESUMEN COMPLETO DEL ANÁLISIS PARA PUNTUACIÓN Y CONCLUSIÓN",
        "company": "PERFIL DE LA EMPRESA",
        "biz_model": "MODELO DE NEGOCIO",
        "traction": "TRACCIÓN",
        "risks": "RIESGOS",
        "risk_narrative": "NARRATIVA DE RIESGOS",
        "instructions": "Aplica las reglas de calibración y los scoring caps del DATA COVERAGE ASSESSMENT. summary: 150-250 palabras específicas y fundamentadas. key_strengths/key_concerns: mín. 3 elementos con evidencia concreta. key_questions: mín. 5. next_steps: mín. 3.",
        "schema": "Devuelve un objeto JSON siguiendo este esquema exacto:",
    },
    "en": {
        "header": "FULL ANALYSIS SUMMARY FOR SCORING AND CONCLUSION",
        "company": "COMPANY PROFILE",
        "biz_model": "BUSINESS MODEL",
        "traction": "TRACTION",
        "risks": "RISKS",
        "risk_narrative": "RISK NARRATIVE",
        "instructions": "Apply the calibration rules and scoring caps from the DATA COVERAGE ASSESSMENT. summary: 150-250 specific evidence-grounded words. key_strengths/key_concerns: min. 3 items with concrete evidence. key_questions: min. 5. next_steps: min. 3.",
        "schema": "Return a JSON object matching this exact schema:",
    },
    "fr": {
        "header": "RÉSUMÉ COMPLET DE L'ANALYSE POUR LA NOTATION ET LA CONCLUSION",
        "company": "PROFIL DE L'ENTREPRISE",
        "biz_model": "MODÈLE D'AFFAIRES",
        "traction": "TRACTION",
        "risks": "RISQUES",
        "risk_narrative": "RÉCIT DES RISQUES",
        "instructions": "Appliquez les règles de calibration et les plafonds de scoring du DATA COVERAGE ASSESSMENT. summary : 150-250 mots spécifiques et fondés sur des preuves. key_strengths/key_concerns : min. 3 éléments avec preuves concrètes. key_questions : min. 5. next_steps : min. 3.",
        "schema": "Retournez un objet JSON correspondant à ce schéma exact:",
    },
    "de": {
        "header": "VOLLSTÄNDIGE ANALYSEZUSAMMENFASSUNG FÜR BEWERTUNG UND SCHLUSSFOLGERUNG",
        "company": "UNTERNEHMENSPROFIL",
        "biz_model": "GESCHÄFTSMODELL",
        "traction": "TRAKTION",
        "risks": "RISIKEN",
        "risk_narrative": "RISIKONARRATIV",
        "instructions": "Wende die Kalibrierungsregeln und Scoring-Obergrenzen aus dem DATA COVERAGE ASSESSMENT an. summary: 150-250 spezifische, evidenzbasierte Wörter. key_strengths/key_concerns: mind. 3 Einträge mit konkreten Belegen. key_questions: mind. 5. next_steps: mind. 3.",
        "schema": "Gib ein JSON-Objekt zurück, das diesem genauen Schema entspricht:",
    },
    "it": {
        "header": "RIEPILOGO COMPLETO DELL'ANALISI PER PUNTEGGIO E CONCLUSIONE",
        "company": "PROFILO AZIENDALE",
        "biz_model": "MODELLO DI BUSINESS",
        "traction": "TRAZIONE",
        "risks": "RISCHI",
        "risk_narrative": "NARRATIVA DEI RISCHI",
        "instructions": "Applica le regole di calibrazione e i cap di scoring dal DATA COVERAGE ASSESSMENT. summary: 150-250 parole specifiche e fondate su prove. key_strengths/key_concerns: min. 3 elementi con prove concrete. key_questions: min. 5. next_steps: min. 3.",
        "schema": "Restituisci un oggetto JSON corrispondente a questo schema esatto:",
    },
}


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    return f"""{opener}

You are a senior M&A analyst scoring a company pre-screening report.
Goal: assess if this company is worth investigating as an acquisition target — NOT whether it is good in general.
Be precise and evidence-grounded. If evidence is limited, scores must reflect that limitation.

DIMENSION WEIGHTS:
  business_model:       25%  — recurring revenue, defensibility, scalability
  traction_and_growth:  20%  — verifiable external growth signals
  risk_profile:         20%  — financial, legal, operational risks (low risk = high score)
  management_and_team:  15%  — stability, depth, retention risk
  competitive_position: 10%  — market standing, differentiation
  acquirability:        10%  — realistic acquisition candidate

overall_score = (biz×0.25)+(traction×0.20)+(risk×0.20)+(mgmt×0.15)+(comp×0.10)+(acq×0.10)
Compute this formula explicitly. Do not guess.

ACQUIRABILITY:
  HIGH (8-10): SME, identifiable owner, clear structure, no blockers, acquirable size.
  MEDIUM (4-7.9): VC-backed, family business, some complexity; also entity_mapping_required.
  LOW (1-3.9): Big Four/partnerships, unicorn, public company, state-owned,
               OR entity_detection_status = "structurally_non_acquirable" (enforced cap ≤ 2.0).
  MISSING LEGAL DATA / entity_mapping_required: Score 4.0–7.0 based on inferred structure,
  sector, size, and available signals. Mark evidence_quality="limited" and note "requires legal
  structure mapping / subject to verification" in rationale. Do NOT score LOW (≤ 3.9) solely
  because legal data was not found publicly — that alone is not a structural barrier.
  Positive acquirability signals even without registry data: prior funding rounds, institutional
  investment, app store developer name, news of prior acquisition, clear product/brand identity.

CALIBRATION:
  Big Four → acquirability 1.0, overall 5.5-6.0 ("Interesante con dudas")
  Solid SME, clear ownership → acquirability 9.0, overall ~6.9
  Company with distress signals → overall 2.0-4.0

PRE-SCREENING PRINCIPLE (non-negotiable):
This is a public-source M&A pre-screening report. Its purpose is to determine whether this
company is worth investigating further as an acquisition target — NOT to complete a valuation
or substitute for financial due diligence. Missing private financial data (ARR, EBITDA, margins,
churn, cap table, audited accounts) is EXPECTED at this stage. It reduces confidence and
generates due diligence questions — it does NOT automatically depress the score or generate a
high-severity risk.

SCORING PRINCIPLE — SCORE AND CONFIDENCE ARE INDEPENDENT:
Scores measure BUSINESS QUALITY based on available evidence.
Confidence levels measure DATA RELIABILITY. Missing data reduces confidence, NOT business scores.
Absence of private financial data for a private/startup company is a confidence reducer and a
due diligence item — never a score penalty and never a high-severity risk by itself.

SCORE CAPS — apply ONLY for explicit negative evidence, never for missing data:
- Active legal issues / insolvency / fraud → reduce risk_profile proportionally to severity
- Non-acquirable structure (network_firm, partnership_llp, nonprofit_guarantee, consortium):
  → acquirability ≤ 2.0 (enforced programmatically — do not override; see DATA COVERAGE ASSESSMENT)
- Verified poor performance (confirmed high churn from external reviews, proven product failures):
  → reduce affected dimension score based on severity of the external evidence

DATA GAPS → reduce evidence_quality per dimension, NOT dimension scores:
- Sparse/absent traction signals: set traction_and_growth evidence_quality="insufficient"
  Score the dimension based on what can be reasonably inferred from available signals.
- No identifiable executives: set management_and_team evidence_quality="insufficient"
  Score based on governance indicators, team size signals, or sector norms.
- No legal/registry confirmation: set acquirability evidence_quality="limited"
  Mark acquirability rationale as "requires verification" — do NOT classify as non-acquirable.
- No market comparables: set competitive_position evidence_quality="limited" or "insufficient"
  Score based on product differentiation and positioning signals.
- All evidence self-reported: set confidence="low". Scores still reflect the apparent business quality.

EXTRACTION FAILURE ≠ BUSINESS WEAKNESS (non-negotiable):
Distinguish three fundamentally different data situations:
1. MISSING PUBLIC DATA (private/startup non-disclosure): company does not file mandatory
   disclosures — expected and normal. → reduce confidence/evidence_quality only.
2. EXTRACTION/PIPELINE FAILURE (known company, data not retrieved):
   - DATA COVERAGE ASSESSMENT shows "Established company = YES" but executives list is empty
     → management_and_team: score as "not assessable from extracted sources"; do NOT score
     as if leadership is weak or absent. evidence_quality="insufficient".
   - DATA COVERAGE ASSESSMENT shows established company but zero news retrieved
     → traction_and_growth: do NOT treat as "no media presence"; it is a retrieval
     limitation. Base score on available signals (app store, web traffic, BORME, Wikipedia).
   - entity_detection_status = "entity_mapping_required"
     → Do NOT write "existence cannot be confirmed" in summary or any field.
     The entity likely exists — the pipeline did not map it. Say "requires verification."
3. NEGATIVE EVIDENCE (explicit contradictions, fraud, insolvency, sanctions):
   → this is the ONLY situation that justifies LOW dimension scores or HIGH-severity risks.

MODEL-BASED HEURISTICS (use as defaults when LLM module returned "unknown" — see DATA COVERAGE ASSESSMENT):
- SaaS B2B → assume recurrence=high, scalability=high (subscription model, near-zero marginal delivery cost)
- Marketplace → assume scalability=high, risk=medium/high (network effects but liquidity dependency)
- Asset-heavy (manufacturing, industrial, logistics, hospitality) → assume scalability=medium

EVIDENCE QUALITY (required per dimension):
- "sufficient": key facts verified from ≥2 independent external sources (any type)
- "limited": main claims supported by 1 external source or mostly website, some external corroboration
- "insufficient": exclusively self-reported; no external corroboration of any kind available

EPISTEMIC LANGUAGE RULES (non-negotiable):
When writing rationales, summaries, and narrative fields, use precise epistemic markers:
- Use "confirmed" or "verified" ONLY when an independent external source supports the claim.
- Use "self-reported" when the claim comes exclusively from the company's own website.
- Use "partially verified" when external evidence exists but is incomplete or from a single source.
- Use "not independently verified" instead of "unknown" when the company likely has this data
  but it is not accessible from public sources — e.g. financials for a private company.
- Use "not detectable in public sources" instead of "not found" when the data could exist
  but was not discoverable from the available sources.
- Reserve "unknown" for cases where the existence of the data itself is unclear.

READINESS ASSESSMENT (required):
- financial_data: "high" if revenue/EBITDA/growth from external source; "medium" if registry
  confirms entity but no financials; "low" if no financial data or registry confirmation at all.
  PRIVATE/STARTUP: "low" is expected and acceptable — frame as a due diligence item, never
  as a negative signal about the company's character or transparency.
- legal_entity: "high" if company registry verified (BORME, OpenCorporates, filings);
  "medium" if entity_detection_status = "entity_mapping_required" (entity almost certainly
  exists but legal name was not extracted from public sources — requires verification, not
  a barrier); "low" ONLY if entity_detection_status = "unknown" (insufficient signals) or
  "structurally_non_acquirable" (confirmed structural barrier).
  Do NOT assign "low" merely because a private/startup lacks public registry data — that
  is entity_mapping_required, which maps to "medium".
- management_visibility: "high" if ≥2 named executives found in any source (website, news,
  registry filings, Wikipedia); "medium" if 1 executive identified; "low" if none detectable
- market_validation: "high" if press/analyst/comparables available; "medium" if technical/
  institutional sources confirm market presence (e.g. GitHub stars, SimilarWeb rank, sector
  directories) without mainstream press; "low" if website-only
- overall: derive from the worst-performing dimension
- When overall readiness is "low" AND entity_detection_status ≠ "structurally_non_acquirable",
  use "Activo atractivo sujeto a verificación" as overall_label if score would otherwise be
  "Interesante con potencial" or "Alta prioridad".
  Do NOT apply "Activo atractivo sujeto a verificación" when entity_detection_status =
  "structurally_non_acquirable" — in that case use "Estructura no adquirible..." instead.

NETWORK / PARTNERSHIP / NON-ACQUIRABLE STRUCTURE RULE (non-negotiable):
APPLIES ONLY when DATA COVERAGE ASSESSMENT shows entity_detection_status =
"structurally_non_acquirable" — i.e. structure_type confirmed as "network_firm",
"partnership_llp", "nonprofit_guarantee", or "consortium" AND group_level_acquirable = false.
Do NOT apply this rule when entity_detection_status = "entity_mapping_required": that means
the entity exists but was not extracted from public sources — it is NOT a structural barrier.
When entity_detection_status = "structurally_non_acquirable":
- acquirability dimension score MUST be 1.0–2.0. This cap is enforced programmatically.
- overall_label MUST be "Estructura no adquirible como grupo — analizar activos o filiales"
  (do not use "Interesante con potencial", "Alta prioridad", or any standard M&A label).
- investment_thesis MUST focus exclusively on carve-out or member-firm acquisition
  opportunities. Do NOT frame the group itself as an M&A target.
- summary MUST explicitly explain the structural barrier to group-level acquisition.
- key_questions MUST include specific questions about individual entity structures
  and carve-out feasibility, NOT about group-level acquisition.
- Do NOT use phrases like "potencial de adquisición del grupo" or "acquisition of [company]"
  when the group is not acquirable — that would be analytically incorrect.

ACQUIRABILITY — GROUP vs. SUBSIDIARY DISTINCTION (general rule):
When evidence suggests the target is a large conglomerate, publicly listed group, or
multinational corporation, distinguish clearly between:
- Group-level acquirability: LOW (1-3) — complex capital structure, public market valuation,
  regulatory exposure, anti-trust risk. Score here if the target is clearly a listed entity
  or a group that could not realistically be acquired whole by a typical strategic buyer.
- Division/subsidiary/asset-level acquirability: MEDIUM-HIGH (5-8) — realistic for strategic
  buyers seeking specific business units, technologies, or geographies.
If the company is a large/listed entity, set acquirability to LOW for group-level and
explain in the rationale that specific divisions or assets may be separately acquirable.
Do NOT apply LOW acquirability to a subsidiary that could realistically be carved out as a
standalone acquisition target — evaluate the subsidiary on its own merits.

SOURCE ATTRIBUTION (required for traceability):
In score_rationale and each dimension rationale, tag the evidentiary basis:
- [external] for claims from news articles, Wikipedia, registries, Glassdoor, or any
  third-party source independent of the company.
- [self-reported] for claims sourced exclusively from the company's own website.
- [inferred] for analytical inferences with no direct evidence.
This tagging makes the analysis defensible and distinguishes verified facts from inferences.

SCORE FINALITY RULE (non-negotiable):
- overall_score = (weighted formula result) AFTER applying mandatory caps. Nothing else.
- NEVER apply an upward "potential bonus", "strategic upside adjustment", or any upward
  revision after computing the capped score. There is no "potential bonus" step.
- If caps reduce the formula result, the final overall_score MUST be ≤ the lowest applicable cap.
- Upside cases, potential, and strategic fit belong ONLY in investment_thesis, never in overall_score.
- score_rationale must be 2-3 sentences explaining ONLY the decisive qualitative factors and
  which caps were applied. Do NOT list intermediate arithmetic steps or multiple score values
  in score_rationale — the system will display the final score separately. A single score value
  appears at the end: "Final score: X.X". No other numeric values in this field.

MANDATORY RULES:
1. Compute overall_score from weighted formula. Show work in score_rationale.
2. Use the FULL scale 1.0-10.0. Scores clustering 6-8 = insufficient differentiation.
3. Acquirability is the most differentiating dimension — score it aggressively.
4. Active distress signals → overall ≤ 3.5. Unacquirable entity → acquirability ≤ 2.0.
5. EPISTEMIC: Never write "strong traction", "market leader", "established client base" as fact
   without specific external evidence. Self-reported claims must be labeled as such.
   If a data point is unknown, state it explicitly — do not fill with plausible-sounding prose.
6. NON-REDUNDANCY: summary, key_strengths, and key_concerns must SYNTHESIZE, not echo.
   Do not repeat verbatim observations already present in the business model description,
   traction growth_narrative, or risk narrative provided as context. Each item must add
   analytical value — derive higher-level conclusions rather than restating what was already
   written. A reader who has seen those sections should learn something new here.

EVIDENCE CONSISTENCY RULE (non-negotiable):
When a business model dimension (recurrence, scalability, etc.) is reported as "unknown":
1. First check if a MODEL-BASED HEURISTIC applies (SaaS B2B, Marketplace, Asset-heavy — see above).
   If yes: apply the heuristic explicitly and state "heuristic applied: [reason]" in the rationale.
2. If no heuristic applies: acknowledge uncertainty — do NOT write confident claims for that dimension.
   Use "cannot be determined from available evidence" or "not independently verified".
3. FORBIDDEN patterns (these are analytical contradictions):
   - Writing "high scalability" or "excellent recurrence" in a rationale when the module field is "unknown"
     and no heuristic overrides it.
   - Claiming "strong traction" or "established client base" without specific external evidence.
   - Claiming "market leader" or "leading position" without citing a specific external source.
4. If contradictions cannot be resolved: score conservatively and state the uncertainty explicitly.
   Contradiction between structured field ("unknown") and confident narrative = unreliable analysis.

PUBLIC COMPANY CALIBRATION (apply ONLY when DATA COVERAGE ASSESSMENT shows listing_status = public):
Public companies file mandatory periodic disclosures (annual reports, 10-K, 6-K, proxy statements).
- If financial data was NOT extracted: this is a SCRAPING/EXTRACTION LIMITATION, not business opacity.
  → Do NOT penalize financial transparency. readiness.financial_data = "medium" minimum.
  → Do NOT set confidence="low" solely because financial details were not scraped.
- Management and board: mandatory disclosure for listed companies means leadership is publicly known.
  → readiness.management_visibility = "medium" minimum even if names were not extracted.
  → If executives are absent from the extracted data: flag as extraction gap, not "no leadership".
- Scoring implication: public companies have higher baseline information availability than private ones.
  → An opaque public company that appears to hide information is a RED FLAG worth noting explicitly,
    not a reason to lower the score for "missing data" in the same way as an opaque private startup.
  → Score the business on what IS known; apply data-absence penalties only to truly unverifiable claims.

PRIVATE COMPANY CALIBRATION (apply when DATA COVERAGE ASSESSMENT shows listing_status = private, startup, or subsidiary):
Private and startup companies do not file mandatory public disclosures. Absence of the following
is NORMAL, EXPECTED, and NOT a red flag or sign of opacity:
  ARR / MRR / EBITDA / net margin / unit economics / churn / LTV / CAC
  Shareholder cap table / ownership percentages / investor names (unless announced publicly)
  Internal financial statements / audited accounts
  Named employees beyond the founding team (for early-stage)
  Detailed product roadmap or customer names
Rules when listing_status = private or startup and financial/operating data is absent:
- DO NOT describe absence as "critical opacity", "critical red flag", or "lack of transparency".
- DO describe it as "limited public disclosure" or "private-company disclosure limitation".
- These absences belong exclusively in key_questions and next_steps as items to validate
  in due diligence — NOT as high-severity risks in key_concerns.
- readiness.financial_data = "low" is acceptable and expected; frame it as a verification
  gap, never as a character flaw or negative signal about the company.
Exception — absence DOES become a genuine risk when there is explicit contradictory evidence:
  material contradictions between stated scale and available signals, fraud signals, regulatory
  sanctions, insolvency proceedings, litigation, credible negative press, or data that is
  provably false. Mere absence without contradiction is always neutral for private/startup targets.

ENTITY DETECTION VS ACQUIRABILITY (non-negotiable):
The DATA COVERAGE ASSESSMENT includes entity_detection_status. Apply these rules strictly:

entity_detection_status = "structurally_non_acquirable":
  → Structure confirmed as network/partnership/non-profit/consortium with group_level_acquirable=false
  → acquirability MUST be ≤ 2.0 (enforced programmatically)
  → overall_label MUST be "Estructura no adquirible como grupo — analizar activos o filiales"
  → Frame investment_thesis around carve-out or individual entity opportunities only
  → This is the ONLY case where "Estructura no adquirible..." label is permitted

entity_detection_status = "entity_mapping_required":
  → Company almost certainly HAS a legal entity — it was NOT extracted, not absent
  → DO NOT classify as non-acquirable for this reason alone
  → DO NOT use "Estructura no adquirible..." label
  → acquirability: score 4.0–7.0 based on other evidence (ownership complexity, size, sector)
  → Rationale must state "requires legal structure mapping / subject to verification"
  → Positive signals that support acquirability: prior funding rounds, institutional investment,
    app store developer/legal name, news coverage, acquisition history, clear brand identity
  → overall_label: use standard score-based label

entity_detection_status = "verified_entity":
  → Legal entity confirmed — score acquirability on business fundamentals and ownership complexity

entity_detection_status = "unknown":
  → Insufficient signals — reduce evidence_quality to "limited" or "insufficient"
  → Apply conservative but not punitive acquirability scoring (typically 4.0–6.0)
  → Do NOT score acquirability ≤ 2.0 on "unknown" alone

UNKNOWN ≠ NEGATIVE EVIDENCE (non-negotiable):
These data states are strictly NEUTRAL — they reduce confidence and evidence_quality but
NEVER justify a high-severity risk entry or a low dimension score by themselves:
  unknown / not_detected / not available / missing public data
  no registry found / no BORME entry / no OpenCorporates match
  no named executives in public sources
  no financial statements / no ARR / no EBITDA
  no cap table / no shareholder register
  no market comparables / no analyst coverage
  no SimilarWeb data / no GitHub metrics
Data absence → reduce evidence_quality ("limited" or "insufficient"), NOT dimension scores.
Scores are penalized ONLY for EXPLICIT NEGATIVE EVIDENCE: litigation, fraud, regulatory
sanctions, insolvency, confirmed negative press, operational failures, material contradictions
between self-reported claims and external evidence, customer churn confirmed externally.
Applying high-severity scores or labels for data absence alone is an analytical error.

RISK CONSOLIDATION RULE (non-negotiable):
When multiple potential risk entries originate from the SAME underlying cause (typically:
limited public disclosure for a private/startup company), they MUST be merged into one.
Do NOT generate 3 separate high-severity risks for:
  "financial opacity" + "lack of retention metrics" + "unverified unit economics"
when all three stem from a single cause: the company does not publish internal operating data.
Instead generate ONE consolidated risk: "limited disclosure — financial and operating
validation required", rated:
  MEDIUM for known private/startup companies with coherent external evidence
  HIGH only if the absence of data materially contradicts the company's claimed scale,
       stage, or external signals (e.g., claims enterprise scale but zero institutional footprint)
All other risks must be substantively independent: competition, regulation, unit economics
substance, operational dependency, customer concentration, market dynamics, technology
defensibility, debt/leverage, litigation, key-person risk, execution risk, etc.

SCORE-TO-LABEL:
  9.0-10.0 → "Oportunidad excepcional" / high
  7.5-8.9  → "Alta prioridad" / high
  6.0-7.4  → "Interesante con potencial" / interesting_with_doubts
  4.5-5.9  → "Interesante con dudas" / interesting_with_doubts
  3.0-4.4  → "Baja prioridad" / low
  1.0-2.9  → "No recomendado" / low
  0.0      → "Información insuficiente" / insufficient_data

Output rules:
- overall_score: float 0.0-10.0 one decimal. Each dimension score: float 1.0-10.0.
- score_rationale: 2-3 sentences on decisive qualitative factors + caps applied. End with "Final score: X.X". No other numbers.
- summary: 150-250 words of specific, evidence-grounded prose. No generic filler.
- key_strengths/key_concerns: minimum 3 each, grounded in specific evidence only.
- key_questions: minimum 5 specific answerable questions.
- next_steps: minimum 3 concrete actionable steps."""


async def run_conclusion(
    classification: Dict[str, Any],
    business_model: Dict[str, Any],
    traction: Dict[str, Any],
    risks: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
    normalized: Dict[str, Any] = None,
    management: Dict[str, Any] = None,
    corporate_structure: Dict[str, Any] = None,
) -> Dict[str, Any]:
    risk_items: List[Dict[str, Any]] = risks.get("risks", [])
    high_risks = [r for r in risk_items if r.get("severity") == "high"]
    medium_risks = [r for r in risk_items if r.get("severity") == "medium"]
    signals = traction.get("signals", [])

    # ── Data coverage assessment (drives scoring caps) ─────────────────
    traction_availability = traction.get("data_availability", "unknown")
    external_signals = [
        s for s in signals
        if s.get("source") not in ("website",) and s.get("evidence_type") != "unverifiable"
    ]

    _norm = normalized or {}
    evidence_profile = _norm.get("evidence_profile") or {}
    coverage_tier = evidence_profile.get("coverage_tier", "sparse")
    _tier_rich     = coverage_tier == "rich"
    _tier_moderate = coverage_tier == "moderate"
    _tier_relaxed  = _tier_rich or _tier_moderate   # both get relaxed traction treatment

    # ── External evidence classification ─────────────────────────────────
    # Use the evidence_profile directly (set by normalizer from actual scraped data).
    # Do NOT derive from traction narrative strings — those are LLM-generated and fragile.
    _news_count = evidence_profile.get("news_article_count", 0)
    has_external_news = _news_count >= 1

    # Non-news external validation: registry/institutional/technical/market sources.
    # These are the primary evidence channel for B2B, industrial, niche, and deep-tech
    # companies that rarely appear in general press but have strong institutional footprints.
    has_non_news_external = evidence_profile.get("has_any_external_non_news", False)

    # Any independent external evidence — news OR institutional/registry/technical
    has_any_external = has_external_news or has_non_news_external

    # ── Corporate structure signals (entity type for acquirability enforcement) ─
    _corp = corporate_structure or {}
    _acq_assessment = _corp.get("acquirability_assessment") or {}
    _struct_type = _acq_assessment.get("structure_type", "unknown")
    _group_acquirable = _acq_assessment.get("group_level_acquirable")  # True/False/None
    _carveout_relevant = _acq_assessment.get("carveout_relevant")
    _acq_struct_notes = (_acq_assessment.get("acquirability_notes") or "")[:300]

    # Management proxy: prefer actual management module output over heuristics
    _mgmt_executives = (management or {}).get("executives", []) if management else []
    has_executives = (
        bool(_mgmt_executives)
        or evidence_profile.get("likely_leadership_visible", False)
    )

    # Self-reported: no external evidence of any kind AND sparse traction
    # (was previously news-only; now correctly ignores institutional/registry sources)
    all_self_reported = (
        traction_availability == "sparse"
        and not has_any_external
        and len(external_signals) < 2
    )

    # ── Company type: public vs private/startup ───────────────────────────
    _listing_status = (classification.get("listing_status") or "unknown").lower()
    _is_public_company = _listing_status == "public"
    _is_private_or_startup = _listing_status in ("private", "startup", "subsidiary")

    # ── Model-based heuristics ────────────────────────────────────────────
    # Derive structural defaults for recurrence/scalability when the business model
    # module returned "unknown". Applied in the prompt as scoring guidance.
    _business_type = (classification.get("business_type") or "").lower()
    _biz_b2b_c = (classification.get("b2b_or_b2c") or "").lower()
    _model_type_bm = (business_model.get("model_type") or "").lower()
    _bm_recurrence = (business_model.get("recurrence") or "unknown").lower()
    _bm_scalability = (business_model.get("scalability") or "unknown").lower()

    _is_saas_b2b = (
        ("saas" in _business_type or "saas" in _model_type_bm)
        and _biz_b2b_c in ("b2b", "b2b2c", "both")
    )
    _is_marketplace = (
        "marketplace" in _business_type or "marketplace" in _model_type_bm
    )
    _is_asset_heavy = any(
        t in _business_type
        for t in ("manufacturing", "industrial", "logistics", "real_estate",
                  "hospitality", "retail", "supermarket", "restaurant")
    )

    _model_hint = ""
    if _is_saas_b2b:
        _model_hint = (
            "SaaS B2B confirmed — structural default: recurrence=high, scalability=high "
            "(apply unless contradicted by explicit negative evidence)"
        )
        if _bm_recurrence == "unknown":
            _bm_recurrence = "high"
        if _bm_scalability == "unknown":
            _bm_scalability = "high"
    elif _is_marketplace:
        _model_hint = (
            "Marketplace confirmed — structural default: scalability=high, "
            "risk=medium/high (network effects + liquidity risk)"
        )
    elif _is_asset_heavy:
        _model_hint = (
            "Asset-heavy model confirmed — structural default: scalability=medium, "
            "risk depends on capital intensity and asset utilization"
        )

    # ── Established company detection ─────────────────────────────────────
    # Companies with multiple corroborating signals should not receive aggressive
    # data-absence caps. Their evidence profile already reflects limited scraping
    # reach, not limited business substance.
    _geography = classification.get("geography") or []
    _geo_count = len(_geography) if isinstance(_geography, list) else 0
    _is_established_company = (
        evidence_profile.get("is_high_visibility", False)
        or coverage_tier == "rich"
        or (_geo_count >= 2 and has_external_news)
        or (_geo_count >= 3 and has_non_news_external)
        or (has_external_news and has_non_news_external)
    )

    # Market data: SimilarWeb, ≥4 external signals, rich tier, or moderate + any external
    has_market_data = (
        bool(_norm.get("similarweb_data"))
        or len(external_signals) >= 4
        or _tier_rich
        or (_tier_moderate and has_any_external)
    )
    # Legal/registry data: explicit registry OR rich tier OR moderate tier with any registry signal
    has_legal_data = (
        bool((_norm.get("corporate_data") or {}).get("legal_name"))
        or bool(_norm.get("borme_entries"))
        or bool(classification.get("factual_profile", {}).get("corporate_data", {}).get("legal_name"))
        or _tier_rich
        or (_tier_moderate and evidence_profile.get("has_corporate_registry", False))
    )

    # ── Entity detection status ───────────────────────────────────────────
    # Distinguishes structurally non-acquirable entities from those that merely
    # need legal-entity mapping. Prevents absence of public registry data from
    # being misread as a structural acquisition barrier.
    _entity_detection_status = _infer_entity_detection_status(
        struct_type=_struct_type,
        group_acquirable=_group_acquirable,
        has_legal_data=has_legal_data,
        listing_status=_listing_status,
        is_established=_is_established_company,
        has_any_external=has_any_external,
    )

    # ── Disclosure interpretation ─────────────────────────────────────────
    # Contextualises absent financial/operating data for the LLM so it doesn't
    # conflate normal private-company non-disclosure with "critical opacity".
    if _is_public_company:
        if has_legal_data:
            _disclosure_interpretation = (
                "public company — registry verified; missing financials = extraction gap, "
                "NOT business opacity"
            )
        else:
            _disclosure_interpretation = (
                "public company — registry not extracted; missing financials may be "
                "extraction gap or red flag — verify before penalising"
            )
    elif _entity_detection_status == "structurally_non_acquirable":
        _disclosure_interpretation = (
            "structurally non-acquirable entity — structural transaction barrier confirmed; "
            "carve-out analysis required"
        )
    elif _is_private_or_startup:
        _disclosure_interpretation = (
            "private/startup — absence of ARR, EBITDA, cap table, churn, margins = "
            "expected limited public disclosure, NOT critical opacity; "
            "financial absences belong in due diligence questions, not as high-severity risks"
        )
    else:
        _disclosure_interpretation = (
            "listing status unknown — apply cautious inference; "
            "missing financial/operating data reduces confidence only, not scores"
        )

    # ── Negative-evidence caps (explicit blockers only — not data absence) ──
    # Caps fire ONLY when there is affirmative evidence of a structural barrier or
    # proven negative outcome. Missing data is handled by confidence_reducers below.
    caps_triggered = []

    # Structural non-acquirability: fires ONLY for explicitly identified non-acquirable
    # structure types. Requires struct_type in the known set to prevent false positives
    # when the LLM returns group_level_acquirable=false for an "unknown" structure
    # (insufficient data, not a structural barrier).
    _NON_ACQUIRABLE_STRUCT_TYPES = frozenset({
        "network_firm", "partnership_llp", "nonprofit_guarantee", "consortium",
    })
    if _group_acquirable is False and _struct_type in _NON_ACQUIRABLE_STRUCT_TYPES:
        caps_triggered.append(
            f"acquirability ≤ 2.0 (structure_type={_struct_type}, "
            f"group_level_acquirable=false — network/partnership/non-profit/consortium)"
        )

    # ── Data-gap confidence reducers ──────────────────────────────────────
    # These do NOT reduce scores. They are passed to the LLM to inform
    # evidence_quality ratings and confidence levels per dimension.
    confidence_reducers = []

    if not _tier_relaxed and (traction_availability == "sparse" or len(external_signals) < 3):
        confidence_reducers.append(
            "traction evidence_quality=limited (sparse/unverified signals — "
            "score based on available evidence, not penalised for absence)"
        )
    if not has_any_external:
        confidence_reducers.append(
            "traction evidence_quality=insufficient (zero external sources — "
            "all traction claims are self-reported)"
        )
    if not has_executives:
        confidence_reducers.append(
            "management evidence_quality=insufficient (no identified executives — "
            "score based on governance signals and sector norms)"
        )
    if not has_market_data:
        confidence_reducers.append(
            "competitive evidence_quality=limited (no market data — "
            "score based on differentiation and positioning signals)"
        )
    if not has_legal_data:
        confidence_reducers.append(
            "acquirability evidence_quality=limited — requires_verification "
            "(legal entity not confirmed externally; do NOT score LOW for this alone)"
        )
    if all_self_reported:
        confidence_reducers.append(
            "overall confidence=low (all evidence exclusively self-reported — "
            "scores reflect apparent quality, not verified quality)"
        )

    _non_news_ext_count = evidence_profile.get("non_news_external_count", 0)
    _is_hv = evidence_profile.get("is_high_visibility", False)

    # ── Computed data confidence ──────────────────────────────────────────
    # Reflects how well the available evidence supports a reliable scoring decision.
    if all_self_reported:
        _computed_confidence = "low"
    elif coverage_tier == "rich" and has_legal_data:
        _computed_confidence = "high"
    elif coverage_tier in ("rich", "moderate") and has_any_external:
        _computed_confidence = "medium"
    elif coverage_tier == "sparse" and has_any_external and has_legal_data:
        _computed_confidence = "medium"
    elif _is_established_company:
        _computed_confidence = "medium"
    else:
        _computed_confidence = "low"

    # Public companies are definitionally established — a pipeline extraction failure
    # (all scrapers returning empty) must NOT produce "low" confidence for a
    # stock-exchange-listed company. Elevate to "medium" as the minimum floor.
    if _is_public_company and _computed_confidence == "low":
        _computed_confidence = "medium"

    # Corporate structure context block (populated when corp_structure module ran)
    _corp_struct_block = ""
    if _struct_type != "unknown" or _group_acquirable is not None:
        _corp_struct_block = (
            f"- Corporate structure type: {_struct_type}\n"
            f"- Group-level acquirable: {_group_acquirable}\n"
            f"- Carve-out relevant: {_carveout_relevant}\n"
            + (f"- Acquirability notes: {_acq_struct_notes}\n" if _acq_struct_notes else "")
        )

    _confidence_reducer_str = (
        "\n".join(f"  · {r}" for r in confidence_reducers)
        if confidence_reducers else "  · none"
    )
    data_coverage_block = (
        f"DATA COVERAGE ASSESSMENT (drives confidence, not scores — see SCORING PRINCIPLE):\n"
        f"- Company listing status: {_listing_status} (public | private | startup | unknown)\n"
        f"- Public company (stock-exchange listed): {'YES — apply PUBLIC COMPANY CALIBRATION rules' if _is_public_company else 'NO'}\n"
        f"- Private or startup: {'YES — apply PRIVATE COMPANY CALIBRATION rules' if _is_private_or_startup else 'NO'}\n"
        f"- Entity detection status: {_entity_detection_status} "
        f"(verified_entity | entity_mapping_required | structurally_non_acquirable | unknown)\n"
        f"- Disclosure interpretation: {_disclosure_interpretation}\n"
        f"- Evidence coverage tier: {coverage_tier} (rich | moderate | sparse | minimal)\n"
        f"- Established company signals: {'YES' if _is_established_company else 'NO'} "
        f"(multi-country + press, or high-visibility, or rich coverage)\n"
        f"- High-visibility company: {'YES' if _is_hv else 'NO'} "
        f"(Wikipedia-confirmed + high web traffic or credible press)\n"
        f"- External source count: {evidence_profile.get('external_source_count', 0)}\n"
        f"- News articles (relevant, filtered): {_news_count}\n"
        f"- Non-news external sources: {_non_news_ext_count} "
        f"(registry/institutional/technical/market — valid for B2B/industrial/niche companies)\n"
        f"- Traction data availability: {traction_availability}\n"
        f"- External verified signals: {len(external_signals)} / {len(signals)} total\n"
        f"- External news coverage: {'YES' if has_external_news else 'NO'}\n"
        f"- Non-news external validation: {'YES' if has_non_news_external else 'NO'} "
        f"(registry, GitHub, SimilarWeb, Glassdoor, Wikipedia)\n"
        f"- Wikipedia available: {'YES' if evidence_profile.get('has_wikipedia') else 'NO'}\n"
        f"- Corporate registry verified: {'YES' if has_legal_data else 'NO'}\n"
        f"- Market data available: {'YES' if has_market_data else 'NO'}\n"
        f"- Identified executives: {len(_mgmt_executives)} named in management module\n"
        f"- All evidence self-reported: {'YES' if all_self_reported else 'NO'}\n"
        f"- Computed data confidence: {_computed_confidence} "
        f"(HIGH=rich+registry | MEDIUM=partial external | LOW=sparse/self-reported)\n"
        f"{_corp_struct_block}"
        f"- Structural score caps (negative evidence only): "
        f"{', '.join(caps_triggered) if caps_triggered else 'none'}\n"
        f"- Data-gap confidence reducers (affect evidence_quality, NOT scores):\n"
        f"{_confidence_reducer_str}\n"
        + (
            f"- Model heuristics: {_model_hint}\n"
            f"  Recurrence (with heuristic): {_bm_recurrence} | "
            f"Scalability (with heuristic): {_bm_scalability}\n"
            if _model_hint else ""
        )
    )

    risk_details = []
    for r in risk_items:
        risk_details.append(
            f"  [{r.get('severity', '?').upper()}] {r.get('name', '?')}: "
            f"{r.get('explanation', '')[:300]}"
        )
    risk_details_str = "\n".join(risk_details) if risk_details else "No risks identified."

    l = _LABELS.get(language or "es", _LABELS["es"])

    user_prompt = f"""
{l['header']}:

{data_coverage_block}
{l['company']}:
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- B2B/B2C: {classification.get('b2b_or_b2c', 'unknown')}
- Main product/service: {classification.get('main_product_or_service', 'unknown')}
- Value proposition: {classification.get('value_proposition_summary', 'unknown')}
- Geography: {classification.get('geography', [])}
- Classification confidence: {classification.get('confidence', 'unknown')}

{l['biz_model']}:
- Type: {business_model.get('model_type', 'unknown')}
- Description: {business_model.get('description', 'unknown')}
- Monetization: {business_model.get('monetization', 'unknown')} — {business_model.get('monetization_detail', '')}
- Recurrence ({business_model.get('recurrence', '?')}): {business_model.get('recurrence_analysis', 'unknown')}
- Scalability ({business_model.get('scalability', '?')}): {business_model.get('scalability_analysis', 'unknown')}
- Differentiation: {business_model.get('differentiation', 'none apparent')}
- Competitive landscape: {business_model.get('competitive_landscape', 'unknown')}
- Business model confidence: {business_model.get('confidence', 'unknown')}

{l['traction']}:
- Data availability: {traction.get('data_availability', 'unknown')}
- Signals found: {len(signals)}
- Growth narrative: {traction.get('growth_narrative', 'No traction narrative available.')}
- News summary: {traction.get('news_summary', 'No news coverage found.')}
- Internal vs external consistency: {traction.get('internal_vs_external_consistency', 'unknown')}
- Data gaps: {traction.get('data_gaps', 'unknown')}

{l['risks']} ({len(risk_items)} identified — {len(high_risks)} high, {len(medium_risks)} medium):
{risk_details_str}

{l['risk_narrative']}: {risks.get('risk_narrative', 'unknown')}

{l['instructions']}

{l['schema']}
{_OUTPUT_SCHEMA}
"""

    result = await gemini_client.generate_structured(
        system_prompt=_build_system_prompt(language),
        user_prompt=user_prompt,
        expected_keys=["overall_score", "overall_label", "dimension_scores", "priority_rating", "summary", "confidence"],
        language=language,
    )

    data = result["data"]

    # Validate and normalise overall_score
    try:
        score = float(data.get("overall_score", 0.0))
        score = max(0.0, min(10.0, round(score, 1)))
    except (TypeError, ValueError):
        score = 0.0
    data["overall_score"] = score

    # Validate priority_rating — derive from score if missing or invalid
    valid_ratings = {"high", "interesting_with_doubts", "low", "insufficient_data"}
    if data.get("priority_rating") not in valid_ratings:
        derived = _score_to_priority_rating(score)
        logger.warning(
            f"Invalid priority_rating: {data.get('priority_rating')!r}. "
            f"Deriving from score {score} → {derived}."
        )
        data["priority_rating"] = derived

    # Validate dimension scores
    dims = data.get("dimension_scores", {})
    for dim in ("business_model", "traction_and_growth", "risk_profile", "management_and_team", "competitive_position", "acquirability"):
        if dim not in dims or not isinstance(dims.get(dim), dict):
            dims[dim] = {"score": 0.0, "rationale": ""}
        else:
            try:
                dims[dim]["score"] = max(0.0, min(10.0, round(float(dims[dim].get("score", 0.0)), 1)))
            except (TypeError, ValueError):
                dims[dim]["score"] = 0.0
    data["dimension_scores"] = dims

    # ── Programmatic cap enforcement ──────────────────────────────────────
    # Only enforces structural/negative-evidence caps — NOT data-absence caps.
    # Data-absence cases are handled by confidence_reducers sent to the LLM.
    _dim_caps: Dict[str, float] = {}
    for _cap in caps_triggered:
        # Structural non-acquirability (explicit negative structural evidence)
        if "acquirability ≤ 2.0" in _cap:
            _dim_caps["acquirability"] = min(_dim_caps.get("acquirability", 10.0), 2.0)

    for _dim, _ceiling in _dim_caps.items():
        if dims.get(_dim, {}).get("score", 0.0) > _ceiling:
            dims[_dim]["score"] = round(_ceiling, 1)
    data["dimension_scores"] = dims

    # ── Score floors for data-absent dimensions (private/startup/subsidiary) ──
    # When evidence_quality == "insufficient" AND no explicit negative cap applies
    # to a dimension, the LLM may have graded it low solely due to missing public
    # data. 5.0 is the correct neutral score: "cannot assess — not negative."
    # This NEVER overrides a cap triggered by explicit negative evidence.
    _FLOOR_SCORE = 5.0
    _DATA_GAP_CATS = frozenset({"opacity", "financial_visibility"})
    _substantive_high_risks = [
        r for r in risk_items
        if r.get("severity") == "high"
        and r.get("risk_category") not in _DATA_GAP_CATS
    ]
    if (_is_private_or_startup or _is_public_company) and _entity_detection_status != "structurally_non_acquirable":
        for _fdim in list(dims.keys()):
            _fdim_data = dims.get(_fdim)
            if not isinstance(_fdim_data, dict):
                continue
            if _fdim in _dim_caps:                           # explicit negative cap → skip
                continue
            if _fdim == "risk_profile" and _substantive_high_risks:  # real high risks → skip
                continue
            if _fdim_data.get("evidence_quality") == "insufficient":
                _fscore = _fdim_data.get("score", 0.0)
                if _fscore < _FLOOR_SCORE:
                    logger.info(
                        "conclusion: 5.0 floor applied to '%s' (was %.1f, "
                        "evidence_quality=insufficient, no negative cap). analysis_id=%s",
                        _fdim, _fscore, analysis_id,
                    )
                    dims[_fdim] = dict(_fdim_data)
                    dims[_fdim]["score"] = _FLOOR_SCORE
        data["dimension_scores"] = dims

    # ── Acquirability floor for entity_mapping_required ───────────────────────
    # entity_mapping_required means the public-source pipeline could not map the
    # precise legal entity — it is a due-diligence task, NOT a structural barrier.
    # The acquirability dimension MUST NOT score below 5.0 on this basis alone,
    # regardless of evidence_quality (LLM may set "limited" even when no
    # structural negative evidence exists, causing unfair score depression).
    if (
        _entity_detection_status == "entity_mapping_required"
        and "acquirability" not in _dim_caps
    ):
        _acq_dim = dims.get("acquirability")
        if isinstance(_acq_dim, dict) and _acq_dim.get("score", 10.0) < _FLOOR_SCORE:
            logger.info(
                "conclusion: 5.0 floor applied to 'acquirability' (was %.1f, "
                "entity_mapping_required — entity-mapping gap, not structural barrier). "
                "analysis_id=%s",
                _acq_dim.get("score"), analysis_id,
            )
            dims["acquirability"] = dict(_acq_dim)
            dims["acquirability"]["score"] = _FLOOR_SCORE
            data["dimension_scores"] = dims

    # Recompute overall_score from (now-capped-and-floored) dimension scores
    _weights = {
        "business_model": 0.25, "traction_and_growth": 0.20, "risk_profile": 0.20,
        "management_and_team": 0.15, "competitive_position": 0.10, "acquirability": 0.10,
    }
    _recomputed = round(sum(dims.get(d, {}).get("score", 0.0) * w for d, w in _weights.items()), 1)
    score = max(0.0, min(10.0, _recomputed))
    data["overall_score"] = score
    # Re-derive priority_rating to stay consistent with the recomputed score
    data["priority_rating"] = _score_to_priority_rating(score)
    # Persist computed data confidence (evidence-driven, independent of score)
    data["computed_data_confidence"] = _computed_confidence
    # Overwrite score_rationale tail so the displayed number always matches the enforced score.
    # Strip ALL language variants that the LLM may have written, then append in the correct language.
    _rationale = str(data.get("score_rationale") or "")
    import re as _re
    _rationale = _re.sub(
        r"\s*(Final score:?|Puntuación final:|Score final:|Punteggio finale:|Gesamtpunktzahl:)\s*[\d.]+\.?",
        "",
        _rationale,
        flags=_re.IGNORECASE,
    ).rstrip(". ")
    _score_label_by_lang = {
        "es": "Puntuación final",
        "en": "Final score",
        "fr": "Score final",
        "de": "Gesamtpunktzahl",
        "it": "Punteggio finale",
    }
    _score_label = _score_label_by_lang.get((language or "es").lower()[:2], "Final score")
    data["score_rationale"] = f"{_rationale}. {_score_label}: {score}."

    record = LLMResult(
        analysis_id=analysis_id,
        module_name="conclusion",
        input_payload={
            "business_type": classification.get("business_type"),
            "model_type": business_model.get("model_type"),
            "traction_data_availability": traction.get("data_availability"),
            "signal_count": len(signals),
            "high_risks_count": len(high_risks),
            "medium_risks_count": len(medium_risks),
            "listing_status": _listing_status,
            "is_public_company": _is_public_company,
            "computed_confidence": _computed_confidence,
        },
        output_payload=data,
        model_used=settings.gemini_model,
        duration_ms=result["duration_ms"],
    )
    db.add(record)
    await db.commit()

    return data
