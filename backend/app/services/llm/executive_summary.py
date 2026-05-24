"""
LLM Module — Executive Summary.

Generates a concise, investor-grade executive summary from the complete assembled
analysis. Runs after all other modules (including the validator) so it always
reflects the final, corrected state of every section.

Output is intentionally short: the executive summary is the first page an investor
reads and must stand entirely on its own. No filler, no generic language.
"""
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.gemini_client import gemini_client
from app.models.llm_result import LLMResult
from app.config import settings
from app.utils.logger import get_logger
from app.services.llm.scoring_guardrails import scrub_executive_summary_text_fields

logger = get_logger(__name__)


_OUTPUT_SCHEMA = """
{
  "what_it_does": "string — 2-3 sharp sentences. What the company sells, to whom, and how it makes money. No buzzwords. No marketing language.",
  "investment_snapshot": [
    "string — EXACTLY 4 bullets. Each must be insightful and decision-relevant. Examples: 'SaaS B2B model with structurally high recurring revenue', 'Strong apparent traction but based exclusively on self-reported metrics', 'Asset-light model with high theoretical scalability — unverified at scale'."
  ],
  "key_risks": [
    "string — EXACTLY 3 bullets. Only the most critical risks. Each must be specific and concrete. No overlap between bullets."
  ],
  "final_verdict": "string — 4-5 sentences. Must answer: (1) Is this an attractive asset? (2) Under what conditions? (3) What is the main blocker? Decisive, analytical tone. No hedging. No generic language."
}
"""


_LANG_OPENERS = {
    "es": "Eres un analista senior de M&A. DEBES responder EXCLUSIVAMENTE en español.",
    "en": "You are a senior M&A analyst. Respond in English.",
    "fr": "Tu es un analyste M&A senior. Tu DOIS répondre EXCLUSIVEMENT en français.",
    "de": "Du bist ein erfahrener M&A-Analyst. Du MUSST AUSSCHLIESSLICH auf Deutsch antworten.",
    "it": "Sei un analista M&A senior. DEVI rispondere ESCLUSIVAMENTE in italiano.",
}

_FORBIDDEN_PHRASES = {
    "es": (
        "Frases PROHIBIDAS (no uses ninguna de éstas):\n"
        "- 'la empresa muestra potencial'\n"
        "- 'con el enfoque adecuado'\n"
        "- 'posicionamiento en el mercado'\n"
        "- cualquier frase genérica que podría aplicarse a cualquier empresa"
    ),
    "en": (
        "FORBIDDEN phrases (do not use any of these):\n"
        "- 'the company shows potential'\n"
        "- 'with the right approach'\n"
        "- 'market positioning'\n"
        "- any generic phrase that could apply to any company"
    ),
    "fr": (
        "Phrases INTERDITES (n'utilisez aucune d'entre elles):\n"
        "- 'l'entreprise montre du potentiel'\n"
        "- 'avec la bonne approche'\n"
        "- 'positionnement sur le marché'\n"
        "- toute phrase générique applicable à n'importe quelle entreprise"
    ),
    "de": (
        "VERBOTENE Phrasen (keine davon verwenden):\n"
        "- 'das Unternehmen zeigt Potenzial'\n"
        "- 'mit dem richtigen Ansatz'\n"
        "- 'Marktpositionierung'\n"
        "- jede generische Formulierung, die auf jedes Unternehmen zutreffen könnte"
    ),
    "it": (
        "Frasi VIETATE (non usare nessuna di queste):\n"
        "- 'l'azienda mostra potenziale'\n"
        "- 'con il giusto approccio'\n"
        "- 'posizionamento di mercato'\n"
        "- qualsiasi frase generica che potrebbe applicarsi a qualsiasi azienda"
    ),
}


def _build_system_prompt(language: str) -> str:
    opener = _LANG_OPENERS.get(language or "es", _LANG_OPENERS["es"])
    forbidden = _FORBIDDEN_PHRASES.get(language or "es", _FORBIDDEN_PHRASES["es"])
    return f"""{opener}

You are writing the EXECUTIVE SUMMARY — the first page of a professional M&A pre-screening report.
This is the only page most investors will read before deciding whether to proceed.

YOUR ROLE:
Extract the decision-relevant insights from a full deep-dive analysis.
Present them in a sharp, investor-grade format. Be a distillation engine, not a rewriter.

RULES:
1. DO NOT rewrite the full analysis. Extract only what matters.
2. DO NOT add new information not present in the analysis.
3. DO NOT change any scores. Use exactly the scores provided.
4. DO NOT dilute conclusions. If the analysis says something is weak, say it.
5. Write like a private equity analyst — decisive, analytical, no hedging.
6. Every sentence must add value. No filler. No repetition.
7. what_it_does: 2-3 sharp sentences describing what the company sells, to whom, and how.
   Not a marketing pitch. Not a vision statement. A factual business description.
8. investment_snapshot: EXACTLY 4 bullets. Each must be insightful, not descriptive.
   Bad: "The company operates in the SaaS sector"
   Good: "SaaS B2B model with structurally high recurring revenue and near-zero marginal cost"
9. key_risks: EXACTLY 3 bullets covering the most critical risks.
   Each must be concrete and specific — no "market risk" or "competition risk" in isolation.
   DISCLOSURE LIMITATION RULE: A "limited financial disclosure" or "missing financial data"
   risk should NOT occupy one of the 3 key_risk slots unless it is rated "high" severity
   AND supported by explicit negative evidence (contradiction, fraud, regulatory action,
   insolvency — not just normal absence for a private/startup company).
   For private/startup/SME companies: prioritise substantive risks (competition, regulation,
   execution, concentration, technology, dependency) as the 3 key risks. If a disclosure
   limitation is included, phrase it as: "Financial performance and unit economics require
   validation in due diligence — not independently verified from public sources."
   FORBIDDEN in key_risks for normal private-company data absence: "critical opacity",
   "impossible to value", "severe lack of transparency", "major financial red flag".
10. final_verdict: 4-5 sentences answering: Is this attractive? Under what conditions? Main blocker?
    Tone: decisive, analytical. No conditional hedging like "could potentially be attractive if..."
    For companies with limited public financials: the verdict should assess whether the asset is
    worth moving to due diligence — not simulate a full valuation. If evidence supports
    business quality, state that clearly. Frame missing financials as a verification step, not a
    barrier to interest.

{forbidden}"""


async def run_executive_summary(
    classification: Dict[str, Any],
    business_model: Dict[str, Any],
    traction: Dict[str, Any],
    risks: Dict[str, Any],
    management: Dict[str, Any],
    competitive_position: Dict[str, Any],
    conclusion: Dict[str, Any],
    analysis_id: str,
    db: AsyncSession,
    language: str = "es",
    analysis_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Generate an executive summary from the assembled analysis.
    Degrades gracefully: if the call fails, returns a minimal fallback dict
    so the pipeline and report are never blocked.
    """
    risk_items = risks.get("risks", [])
    high_risks = [r for r in risk_items if r.get("severity") == "high"]
    top_risks_text = "\n".join(
        f"  [{r.get('severity','?').upper()}] {r.get('name','?')}: {r.get('explanation','')[:200]}"
        for r in risk_items[:5]
    ) or "No risks identified."

    _listing_status = (classification.get("listing_status") or "unknown").lower()
    _is_private_or_startup = _listing_status in ("private", "startup", "subsidiary")

    overall_score = conclusion.get("overall_score", 0.0)
    overall_label = conclusion.get("overall_label", "")
    score_rationale = conclusion.get("score_rationale", "")
    summary = conclusion.get("summary", "")
    investment_thesis = conclusion.get("investment_thesis", "")
    key_strengths = conclusion.get("key_strengths", [])
    key_concerns = conclusion.get("key_concerns", [])

    dims = conclusion.get("dimension_scores", {})
    dims_text = "\n".join(
        f"  {k}: {v.get('score', '?')}/10 — {v.get('rationale', '')[:150]}"
        for k, v in dims.items()
    ) if dims else "  No dimension scores available."

    executives = (management or {}).get("executives", [])
    exec_text = ", ".join(
        e.get("name", "") for e in executives[:3] if e.get("name")
    ) or "Not identified"

    comp_moat = (competitive_position or {}).get("moat_assessment", "")
    comp_position = (competitive_position or {}).get("positioning_narrative", "")

    _disclosure_ctx = (
        "PRIVATE/STARTUP — missing financial data is expected; "
        "disclosure limitation = MEDIUM risk; key_risks should focus on substantive risks"
        if _is_private_or_startup
        else (
            "PUBLIC COMPANY — missing financial data may be extraction gap or genuine red flag"
            if _listing_status == "public"
            else "LISTING STATUS UNKNOWN — treat missing financials as confidence reducer only"
        )
    )

    # Build authoritative calibration override block from pre-computed context.
    # This replaces any independent re-derivation the LLM might otherwise perform
    # from raw module inputs that could re-introduce data-absence-as-weakness framing.
    _ctx = analysis_context or {}
    _cal_financial = _ctx.get(
        "financial_data_absence_interpretation",
        "Missing financial data reduces confidence only — not a score penalty or business weakness.",
    )
    _cal_management = _ctx.get(
        "management_absence_interpretation",
        "Missing executive data is a pipeline extraction limitation — not a leadership weakness.",
    )
    _cal_registry = _ctx.get(
        "registry_absence_interpretation",
        "Missing registry data requires due diligence verification — not a structural acquisition barrier.",
    )
    _calibration_override_block = f"""
AUTHORITATIVE CALIBRATION OVERRIDE (non-negotiable — use these interpretations verbatim):
- Financial data absence: {_cal_financial}
- Management visibility: {_cal_management}
- Registry / legal entity: {_cal_registry}

These are the settled pre-screening interpretations. Do NOT re-derive or override them.
Missing public data reduces confidence and generates due diligence questions,
but MUST NOT be treated as a business weakness unless explicit negative evidence exists."""

    user_prompt = f"""FULL ANALYSIS INPUT — extract only what is decision-relevant.

COMPANY:
- Name: {classification.get('company_name', classification.get('factual_profile', {}).get('name', 'Unknown'))}
- Business type: {classification.get('business_type', 'unknown')}
- Sector: {classification.get('sector', 'unknown')}
- B2B/B2C: {classification.get('b2b_or_b2c', 'unknown')}
- Listing status: {_listing_status} — {_disclosure_ctx}
- Geography: {classification.get('geography', [])}
- Main product/service: {classification.get('main_product_or_service', 'unknown')}
- Value proposition: {classification.get('value_proposition_summary', 'unknown')}

BUSINESS MODEL:
- Type: {business_model.get('model_type', 'unknown')}
- Recurrence: {business_model.get('recurrence', 'unknown')} — {business_model.get('recurrence_analysis', '')[:200]}
- Scalability: {business_model.get('scalability', 'unknown')} — {business_model.get('scalability_analysis', '')[:200]}
- Monetization: {business_model.get('monetization', 'unknown')} — {business_model.get('monetization_detail', '')[:200]}
- Differentiation: {business_model.get('differentiation', 'none apparent')[:200]}

TRACTION:
- Data availability: {traction.get('data_availability', 'unknown')}
- Growth narrative: {traction.get('growth_narrative', 'No traction data.')[:400]}
- News summary: {traction.get('news_summary', 'No news coverage.')[:300]}

RISKS ({len(risk_items)} identified — {len(high_risks)} high severity):
{top_risks_text}

MANAGEMENT:
- Identified executives: {exec_text}
- Team assessment: {(management or {}).get('team_assessment', 'Not assessed')[:200]}

COMPETITIVE POSITION:
- Moat: {comp_moat[:200] if comp_moat else 'Not assessed'}
- Positioning: {comp_position[:200] if comp_position else 'Not assessed'}

FINAL SCORES:
- Overall: {overall_score}/10 — {overall_label}
- Score rationale: {score_rationale[:300]}
{dims_text}

ANALYSIS SUMMARY (already written — use for context, do not copy):
{summary[:500]}

INVESTMENT THESIS (already written — use for context, do not copy):
{investment_thesis[:300]}

KEY STRENGTHS: {key_strengths[:3]}
KEY CONCERNS: {key_concerns[:3]}

CONFIDENCE: {conclusion.get('confidence', 'unknown')}
DATA LIMITATIONS: {conclusion.get('data_limitations', 'None stated')}
PRE-SCREENING DISCLOSURE CONTEXT: {_disclosure_ctx}
{_calibration_override_block}

---
Now generate the executive summary following the output schema exactly.
Return a JSON object:
{_OUTPUT_SCHEMA}"""

    try:
        result = await gemini_client.generate_structured(
            system_prompt=_build_system_prompt(language),
            user_prompt=user_prompt,
            expected_keys=["what_it_does", "investment_snapshot", "key_risks", "final_verdict"],
            language=language,
        )

        data = result["data"]

        # Enforce structural constraints programmatically
        # Trim to exact required counts if LLM over/under-generates
        if isinstance(data.get("investment_snapshot"), list):
            data["investment_snapshot"] = data["investment_snapshot"][:4]
        else:
            data["investment_snapshot"] = []

        if isinstance(data.get("key_risks"), list):
            data["key_risks"] = data["key_risks"][:3]
        else:
            data["key_risks"] = []

        # Copy score fields directly from conclusion — never from LLM output
        data["final_score"] = overall_score
        data["score_label"] = overall_label
        data["priority_rating"] = conclusion.get("priority_rating", "insufficient_data")
        data["computed_data_confidence"] = conclusion.get("computed_data_confidence", "low")

        # Apply deterministic text scrubbing (Rules 1/5/6):
        # ensures external-absence framing, score-attribution, and attractiveness-link
        # language is neutralised in the exec summary just as it is in conclusion_data.
        data = scrub_executive_summary_text_fields(data)

        record = LLMResult(
            analysis_id=analysis_id,
            module_name="executive_summary",
            input_payload={
                "business_type": classification.get("business_type"),
                "overall_score": overall_score,
                "overall_label": overall_label,
                "language": language,
            },
            output_payload=data,
            model_used=settings.gemini_model,
            duration_ms=result["duration_ms"],
        )
        db.add(record)
        await db.commit()

        return data

    except Exception as e:
        # Degrade gracefully — the rest of the report is not affected
        logger.warning(f"Executive summary generation failed for {analysis_id}: {e}")
        return {
            "what_it_does": None,
            "investment_snapshot": [],
            "key_risks": [],
            "final_verdict": None,
            "final_score": overall_score,
            "score_label": overall_label,
            "priority_rating": conclusion.get("priority_rating", "insufficient_data"),
            "computed_data_confidence": conclusion.get("computed_data_confidence", "low"),
        }
