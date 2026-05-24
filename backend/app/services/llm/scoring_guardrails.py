"""
Deterministic scoring guardrails layer.

Applied AFTER run_conclusion, BEFORE run_executive_summary.

Enforces the global pre-screening principle system-wide:
    DATA ABSENCE ≠ BUSINESS WEAKNESS
    DATA ABSENCE affects only CONFIDENCE and DUE DILIGENCE NEEDS.
    DATA ABSENCE never reduces scores or produces negative narrative interpretations.

Six rules implemented here:
  1. SCORING PROTECTION      — strip language attributing score reduction to data absence.
  2. MANAGEMENT FIX          — established company + no extracted executives →
                               extraction limitation, not leadership risk.
  3. CORPORATE STRUCTURE FIX — entity_mapping_required → verification needed,
                               not a structural or existential barrier.
  4. NO NEGATIVE CASCADE     — missing data must not drive overall_label downward.
  5. CONCLUSION CLEANUP      — rewrite text linking data absence to lower attractiveness.
  6. EXTERNAL SIGNALS FRAMING — absence of external signals must never be labelled
                               "crítica", "anomalía", or "fallo del pipeline".
                               Correct frame: "limitación de cobertura de fuentes del análisis".
                               Applies to Spanish and English output alike.

All functions are deterministic (rule-based). No LLM calls.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Validation kill switch ────────────────────────────────────────────────────
# When DISABLE_CALIBRATION=1, the public guardrail functions return their inputs
# unchanged. Used exclusively for validation experiments (mode B in chapter 6
# of the TFG memoria). Has no effect when unset or set to "0".
def _calibration_disabled() -> bool:
    return os.getenv("DISABLE_CALIBRATION", "0") == "1"


# ── Canonical replacement phrases ─────────────────────────────────────────────
# Bilingual variants. Selected via _lang(context) below.

_MGMT_EXTRACTION_LIMITATION_EN = (
    "Executive information was not retrieved by the current extraction pipeline. "
    "This does not reflect a lack of leadership but a data extraction limitation. "
    "Management assessment should be performed during due diligence."
)
_MGMT_EXTRACTION_LIMITATION_ES = (
    "El pipeline de extracción no ha recuperado información sobre los ejecutivos en esta "
    "ejecución. Esto no refleja una ausencia de liderazgo sino una limitación de extracción "
    "de datos. La evaluación del equipo directivo debe realizarse durante el due diligence."
)

_CORP_MAPPING_LIMITATION_EN = (
    "Legal entity mapping was not completed using standard registries. "
    "This is common in pre-screening and requires direct verification during due diligence."
)
_CORP_MAPPING_LIMITATION_ES = (
    "El mapeo de la entidad legal no se ha completado a través de los registros estándar. "
    "Es habitual en pre-screening y requiere verificación directa durante el due diligence."
)

_DATA_ABSENCE_NEUTRAL_EN = (
    "While certain data points are not publicly available, this is expected at the "
    "pre-screening stage and does not detract from the underlying business attractiveness."
)
_DATA_ABSENCE_NEUTRAL_ES = (
    "Aunque ciertos datos no están disponibles públicamente, es lo esperable en la fase de "
    "pre-screening y no resta atractivo al negocio subyacente."
)

_MGMT_KEY_CONCERN_REFRAME_EN = (
    "Management team visibility is limited due to pipeline extraction "
    "constraints, not a confirmed leadership gap. Executive profiles "
    "should be confirmed directly in due diligence."
)
_MGMT_KEY_CONCERN_REFRAME_ES = (
    "La visibilidad del equipo directivo está limitada por restricciones del pipeline de "
    "extracción, no por una carencia confirmada de liderazgo. Los perfiles ejecutivos deben "
    "confirmarse directamente en el due diligence."
)

_CORP_KEY_CONCERN_REFRAME_EN = (
    "Legal entity mapping was not completed from standard public registries. "
    "This requires direct verification in due diligence and does not constitute "
    "a structural barrier to acquisition."
)
_CORP_KEY_CONCERN_REFRAME_ES = (
    "El mapeo de la entidad legal no se ha completado desde registros públicos estándar. "
    "Esto requiere verificación directa durante el due diligence y no constituye una barrera "
    "estructural para la adquisición."
)

_CORP_INLINE_FIX_EN = "legal entity mapping requires direct verification during due diligence"
_CORP_INLINE_FIX_ES = "el mapeo de la entidad legal requiere verificación directa durante el due diligence"

_MGMT_RATIONALE_TAIL_EN = (
    "Evidence quality for this dimension is insufficient due to the extraction "
    "gap, not due to a genuine leadership weakness."
)
_MGMT_RATIONALE_TAIL_ES = (
    "La calidad de la evidencia en esta dimensión es insuficiente por la limitación de "
    "extracción, no por una debilidad real del liderazgo."
)


def _lang(context: Optional[Dict[str, Any]]) -> str:
    """Return 'es' or 'en' (defaults to 'es')."""
    code = ((context or {}).get("language") or "es").lower()
    return "en" if code.startswith("en") else "es"


def _mgmt_extraction_limitation(context: Optional[Dict[str, Any]]) -> str:
    return _MGMT_EXTRACTION_LIMITATION_ES if _lang(context) == "es" else _MGMT_EXTRACTION_LIMITATION_EN


def _corp_mapping_limitation(context: Optional[Dict[str, Any]]) -> str:
    return _CORP_MAPPING_LIMITATION_ES if _lang(context) == "es" else _CORP_MAPPING_LIMITATION_EN


# Backwards-compatible aliases (English defaults, used only if a function calls
# them without a context — should not happen after this patch).
_MGMT_EXTRACTION_LIMITATION = _MGMT_EXTRACTION_LIMITATION_EN
_CORP_MAPPING_LIMITATION = _CORP_MAPPING_LIMITATION_EN
_DATA_ABSENCE_NEUTRAL = _DATA_ABSENCE_NEUTRAL_EN


# ── Score-attribution fixes (Rule 1) ─────────────────────────────────────────
# Phrases that incorrectly attribute score reduction to data absence.
# Each tuple is (bad_phrase_lower, replacement).
# Applied case-insensitively to all narrative text fields.

_SCORE_ATTRIBUTION_FIXES: Tuple[Tuple[str, str], ...] = (
    # Direct "reduces the score" patterns
    ("reduces the score",               "reduces confidence only"),
    ("reduce the score",                "reduce confidence only"),
    ("reducing the score",              "reducing confidence only"),
    ("reduced the score",               "reduced confidence only"),
    # "penalizes" patterns
    ("penalizes the score",             "reduces confidence"),
    ("penalize the score",              "reduce confidence"),
    ("penalising the score",            "reducing confidence"),
    ("penalizing the score",            "reducing confidence"),
    ("penalized the score",             "reduced confidence"),
    ("penalised the score",             "reduced confidence"),
    # "lowers" patterns
    ("lowers the score",                "reduces confidence"),
    ("lower the score",                 "reduce confidence"),
    ("lowering the score",              "reducing confidence"),
    ("lowered the score",               "reduced confidence"),
    # "depresses / limits / constrains" patterns
    ("depresses the score",             "reduces confidence"),
    ("limits the score",                "reduces confidence"),
    ("limits this score",               "reduces confidence"),
    ("constrains the score",            "reduces confidence"),
    # "score is X" passive patterns
    ("score is penalized",              "confidence is reduced"),
    ("score is reduced",                "confidence is reduced"),
    ("score is lowered",                "confidence is reduced"),
    ("score is negatively impacted",    "confidence is reduced"),
    ("score is negatively affected",    "confidence is reduced"),
    # Compound forms
    ("score penalty",                   "confidence reduction"),
    ("scoring penalty",                 "confidence reduction"),
    ("score reduction",                 "confidence reduction"),
    ("negatively impacts the score",    "negatively impacts confidence"),
    ("negatively affect the score",     "negatively affect confidence"),
    ("negatively affecting the score",  "negatively affecting confidence"),
    ("negatively impacts the overall score", "negatively impacts confidence"),
    # "capped due to missing" patterns
    ("capped due to missing data",      "confidence-limited due to missing data"),
    ("capped due to limited data",      "confidence-limited due to limited data"),
    ("score is capped",                 "confidence is limited"),
)


# ── Management-absence patterns (Rule 2) ─────────────────────────────────────
# Phrases that treat executive absence as a business risk rather than an extraction gap.
# (case-insensitive substring match)

_MGMT_ABSENCE_AS_RISK: Tuple[str, ...] = (
    "no executives identified",
    "no executives found",
    "no executives were identified",
    "no executives were found",
    "executives not identified",
    "executives not found",
    "no leadership identified",
    "leadership not identified",
    "no management team identified",
    "management team not identified",
    "management not identified",
    "unable to identify any executives",
    "unable to identify executives",
    "could not identify any executives",
    "could not identify executives",
    "no identifiable executives",
    "no key executives",
    "key executives could not be found",
    "no named executives",
    "named executives not found",
    "no publicly identifiable executives",
    "no publicly known executives",
    "no executives detectable",
)


# ── Corporate-structure-absence patterns (Rule 3) ─────────────────────────────
# Phrases that incorrectly treat registry absence as a structural or existential risk.
# (case-insensitive substring match)

_CORP_ABSENCE_AS_RISK: Tuple[str, ...] = (
    "cannot verify legal existence",
    "cannot verify the legal existence",
    "legal existence cannot be verified",
    "legal existence cannot be confirmed",
    "legal existence could not be verified",
    "entity cannot be verified",
    "entity could not be verified",
    "entity cannot be confirmed",
    "existence cannot be confirmed",
    "existence could not be confirmed",
    "entity may not exist",
    "entity does not exist",
    "no legal entity found",
    "no legal entity identified",
    "legal entity not found",
    "legal entity not identified",
    "legal entity not confirmed",
    "acquisition cannot proceed",
    "acquisition is blocked by missing registry",
    "acquisition is blocked due to missing registry",
    "structural barrier due to missing registry",
    "structural barrier due to absence of registry",
)


# ── Data-absence → attractiveness-reduction patterns (Rule 5) ─────────────────
# Compound phrases that explicitly link data absence to lower attractiveness/investment case.
# More specific than general attractiveness phrases to minimize false positives.

_DATA_ABSENCE_ATTRACTIVENESS: Tuple[str, str] = (
    # (bad_phrase_lower, replacement)
    ("missing data reduces the attractiveness",
     "missing data is expected at this stage and does not reduce the underlying attractiveness"),
    ("missing data reduces attractiveness",
     "missing data is expected at this stage and does not reduce the underlying attractiveness"),
    ("missing data limits the attractiveness",
     "missing data is a due diligence item and does not limit the underlying attractiveness"),
    ("absence of data reduces the attractiveness",
     "absence of public data is expected at pre-screening and does not reduce attractiveness"),
    ("absence of data limits the attractiveness",
     "absence of public data is a due diligence item, not an attractiveness reducer"),
    ("lack of data reduces the attractiveness",
     "lack of public data is expected at pre-screening and does not reduce attractiveness"),
    ("data gaps reduce the attractiveness",
     "data gaps are due diligence items and do not reduce underlying business attractiveness"),
    ("data gaps limit the attractiveness",
     "data gaps are due diligence items, not attractiveness limiters"),
    ("limited visibility reduces the attractiveness",
     "limited public visibility is expected at pre-screening and does not reduce attractiveness"),
    ("limited visibility limits the attractiveness",
     "limited public visibility is a confidence reducer, not an attractiveness limiter"),
    ("missing financial data reduces the attractiveness",
     "missing financial data is expected for a private company and does not reduce attractiveness"),
    ("missing financial data limits the attractiveness",
     "missing financial data is a due diligence item, not an attractiveness limiter"),
    ("absence of financial data reduces",
     "absence of public financial data is expected at this stage and does not reduce"),
    ("lack of financial data reduces",
     "lack of public financial data is expected at pre-screening and does not reduce"),
    ("limited disclosure reduces attractiveness",
     "limited public disclosure is normal at pre-screening and does not reduce attractiveness"),
    ("financial opacity reduces",
     "limited financial visibility at pre-screening does not reduce"),
    ("detracts from the attractiveness",
     "does not detract from the underlying business attractiveness"),
    ("detracts from attractiveness",
     "does not detract from the underlying business attractiveness"),
    ("reduces the investment case",
     "does not reduce the underlying investment case"),
    ("weakens the investment case",
     "does not weaken the underlying investment case — it is a due diligence item"),
    ("limits the investment case",
     "does not limit the underlying investment case"),
    ("makes this a less attractive",
     "does not make this a less attractive"),
    ("makes the asset less attractive",
     "does not make the asset less attractive"),
    ("less attractive due to missing",
     "subject to verification — missing data is expected at this stage"),
    ("less attractive due to limited",
     "subject to verification — limited public data is expected at this stage"),
    ("less attractive due to absence",
     "subject to verification — data absence is expected at this stage"),
)


# ── Rule 6: External-signals-absence framing fixes ───────────────────────────
# Phrases that treat the absence of retrieved external data as a "critical",
# "anomalous", or "pipeline failure" event rather than a routine pre-screening
# coverage limitation.  Applied to ALL companies (public or private) because:
#   • For public / established companies: clearly a pipeline retrieval gap.
#   • For private / startup companies:    expected absence, never "critical".
# Each tuple: (bad_phrase_lower, replacement_text).

_EXTERNAL_ABSENCE_AS_ANOMALY_FIXES: Tuple[Tuple[str, str], ...] = (
    # ── Spanish ──────────────────────────────────────────────────────────────
    # "ausencia crítica" variants
    ("ausencia crítica de validación externa",
     "limitación de cobertura de fuentes del análisis"),
    ("ausencia crítica de señales externas",
     "limitación de cobertura de fuentes del análisis"),
    ("ausencia crítica de datos externos",
     "limitación de cobertura de fuentes del análisis"),
    ("ausencia crítica de información externa",
     "limitación de cobertura de fuentes del análisis"),
    ("ausencia crítica de cobertura externa",
     "limitación de cobertura de fuentes del análisis"),
    ("ausencia critica de validación externa",       # without accent
     "limitación de cobertura de fuentes del análisis"),
    ("ausencia critica de señales externas",
     "limitación de cobertura de fuentes del análisis"),
    # "anomalía" in the context of missing external coverage
    ("anomalía significativa en la cobertura",
     "limitación de cobertura del pipeline de análisis"),
    ("anomalía significativa de cobertura",
     "limitación de cobertura del pipeline de análisis"),
    ("anomalía en la validación externa",
     "limitación de cobertura del pipeline de análisis"),
    ("anomalía de validación externa",
     "limitación de cobertura del pipeline de análisis"),
    ("anomalía crítica de cobertura",
     "limitación de cobertura del pipeline de análisis"),
    # meta-commentary that backfires: mentions "pipeline failure" and then denies it —
    # both halves are wrong; replace with a clean affirmative framing
    ("no debe interpretarse como fallo del pipeline",
     "es una limitación de cobertura del análisis de pre-screening"),
    ("no debe interpretarse como un fallo del pipeline",
     "es una limitación de cobertura del análisis de pre-screening"),
    ("no debe entenderse como fallo del pipeline",
     "debe entenderse como una limitación de cobertura del análisis"),
    ("no debe entenderse como un fallo del pipeline",
     "debe entenderse como una limitación de cobertura del análisis"),
    ("no se trata de un fallo del pipeline",
     "se trata de una limitación de cobertura del análisis"),
    # generic "critical" applied to absence of external sources
    ("falta crítica de validación externa",
     "limitación de cobertura de fuentes del análisis"),
    ("falta crítica de señales externas",
     "limitación de cobertura de fuentes del análisis"),
    # ── English ──────────────────────────────────────────────────────────────
    ("critical absence of external validation",
     "pipeline coverage limitation for this analysis run"),
    ("critical absence of external signals",
     "pipeline coverage limitation for this analysis run"),
    ("critical absence of external data",
     "pipeline coverage limitation for this analysis run"),
    ("critical absence of external coverage",
     "pipeline coverage limitation for this analysis run"),
    ("critical lack of external validation",
     "pipeline coverage limitation for this analysis run"),
    ("critical lack of external signals",
     "pipeline coverage limitation for this analysis run"),
    ("significant anomaly in external coverage",
     "pipeline coverage limitation for this analysis run"),
    ("significant anomaly in coverage",
     "pipeline coverage limitation for this analysis run"),
    ("anomaly in external validation",
     "pipeline coverage limitation for this analysis run"),
    # meta-commentary backfire — English variant
    ("should not be interpreted as a pipeline failure",
     "is a pipeline coverage limitation for this analysis"),
    ("must not be interpreted as a pipeline failure",
     "is a pipeline coverage limitation for this analysis"),
    ("should not be seen as a pipeline failure",
     "is a pipeline coverage limitation for this analysis"),
    ("is not a pipeline failure",
     "is a pipeline coverage limitation for this analysis"),
)


# ── Text helper functions ─────────────────────────────────────────────────────

def _sub_ci(pattern: str, replacement: str, text: str) -> str:
    """Case-insensitive literal string substitution."""
    return re.sub(re.escape(pattern), replacement, text, flags=re.IGNORECASE)


def _contains_any(text: str, phrases: tuple) -> bool:
    """Return True if any phrase appears in text (case-insensitive)."""
    t = (text or "").lower()
    return any(p in t for p in phrases)


def _scrub_score_attribution(text: Optional[str]) -> Optional[str]:
    """Apply Rule 1 fixes: replace score-reduction phrases with confidence-reduction equivalents."""
    if not text:
        return text
    result = text
    for bad, good in _SCORE_ATTRIBUTION_FIXES:
        if bad in result.lower():
            result = _sub_ci(bad, good, result)
    return result


def _scrub_attractiveness_links(text: Optional[str]) -> Optional[str]:
    """Apply Rule 5 fixes: replace data-absence → lower-attractiveness compound phrases."""
    if not text:
        return text
    result = text
    for bad, good in _DATA_ABSENCE_ATTRACTIVENESS:
        if bad in result.lower():
            result = _sub_ci(bad, good, result)
    return result


def _scrub_external_absence_framing(text: Optional[str]) -> Optional[str]:
    """
    Rule 6: Replace phrases that treat absent external signals as "critical",
    "anomalous", or a "pipeline failure".
    Correct framing: routine pre-screening coverage limitation.
    Applies to both Spanish and English output.
    """
    if not text:
        return text
    result = text
    for bad, good in _EXTERNAL_ABSENCE_AS_ANOMALY_FIXES:
        if bad in result.lower():
            result = _sub_ci(bad, good, result)
    return result


def _scrub_field(text: Optional[str]) -> Optional[str]:
    """Apply all text-scrubbing rules to a single text field."""
    if not text:
        return text
    text = _scrub_score_attribution(text)
    text = _scrub_attractiveness_links(text)
    text = _scrub_external_absence_framing(text)
    return text


def _scrub_list(items: Optional[List[str]]) -> Optional[List[str]]:
    """Apply text scrubbing to every string in a list."""
    if not items:
        return items
    return [_scrub_field(item) or item for item in items]


# ── Rule 2: Management fix ────────────────────────────────────────────────────

def _apply_rule_2_management(
    data: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    For established companies where no executives were extracted, replace any
    management rationale that implies leadership risk or absence-as-risk with
    the canonical extraction-limitation text.

    Targets: dimension_scores.management_and_team.rationale
             key_concerns items (reframe, not remove)
    """
    dims = data.get("dimension_scores") or {}
    mgmt_dim = dims.get("management_and_team") or {}
    rationale = mgmt_dim.get("rationale") or ""

    if _contains_any(rationale, _MGMT_ABSENCE_AS_RISK):
        logger.warning(
            "[guardrails] Rule 2: Established company — replacing management rationale "
            "that implies leadership absence as a risk with extraction-limitation framing."
        )
        new_mgmt = dict(mgmt_dim)
        if _lang(context) == "es":
            new_mgmt["rationale"] = _MGMT_EXTRACTION_LIMITATION_ES + " " + _MGMT_RATIONALE_TAIL_ES
        else:
            new_mgmt["rationale"] = _MGMT_EXTRACTION_LIMITATION_EN + " " + _MGMT_RATIONALE_TAIL_EN
        # Preserve score — evidence_quality captures the limitation
        if new_mgmt.get("evidence_quality") not in ("sufficient", "limited"):
            new_mgmt["evidence_quality"] = "insufficient"
        new_dims = dict(dims)
        new_dims["management_and_team"] = new_mgmt
        data = dict(data)
        data["dimension_scores"] = new_dims

    # Reframe any key_concerns that invoke management absence as a risk
    key_concerns: List[str] = list(data.get("key_concerns") or [])
    new_concerns: List[str] = []
    changed = False
    for concern in key_concerns:
        if _contains_any(concern, _MGMT_ABSENCE_AS_RISK):
            logger.info(
                "[guardrails] Rule 2: Reframing management-absence key_concern "
                "for established company: '%.80s'", concern,
            )
            new_concerns.append(
                _MGMT_KEY_CONCERN_REFRAME_ES if _lang(context) == "es"
                else _MGMT_KEY_CONCERN_REFRAME_EN
            )
            changed = True
        else:
            new_concerns.append(concern)
    if changed:
        data = dict(data)
        data["key_concerns"] = new_concerns

    return data


# ── Rule 3: Corporate structure fix ──────────────────────────────────────────

def _apply_rule_3_corporate_structure(
    data: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    For entity_mapping_required, replace forbidden "existence cannot be verified"
    and "critical registry gap" phrases in the acquirability rationale and
    key_concerns with the canonical mapping-limitation text.

    Targets: dimension_scores.acquirability.rationale
             key_concerns items
             summary
    """
    dims = data.get("dimension_scores") or {}
    acq_dim = dims.get("acquirability") or {}
    rationale = acq_dim.get("rationale") or ""

    if _contains_any(rationale, _CORP_ABSENCE_AS_RISK):
        logger.warning(
            "[guardrails] Rule 3: entity_mapping_required — replacing forbidden "
            "corporate-structure language in acquirability rationale."
        )
        fixed = rationale
        inline_fix = _CORP_INLINE_FIX_ES if _lang(context) == "es" else _CORP_INLINE_FIX_EN
        for phrase in _CORP_ABSENCE_AS_RISK:
            if phrase in fixed.lower():
                fixed = _sub_ci(phrase, inline_fix, fixed)
        # Append canonical note if it isn't already present
        canonical_note = _corp_mapping_limitation(context)
        if canonical_note[:40].lower() not in fixed.lower():
            fixed = fixed.rstrip(". ") + ". " + canonical_note
        new_acq = dict(acq_dim)
        new_acq["rationale"] = fixed
        new_dims = dict(dims)
        new_dims["acquirability"] = new_acq
        data = dict(data)
        data["dimension_scores"] = new_dims

    # Fix key_concerns that invoke corporate-structure absence as a barrier
    key_concerns: List[str] = list(data.get("key_concerns") or [])
    new_concerns: List[str] = []
    changed = False
    for concern in key_concerns:
        if _contains_any(concern, _CORP_ABSENCE_AS_RISK):
            logger.info(
                "[guardrails] Rule 3: Reframing corporate-structure key_concern: '%.80s'",
                concern,
            )
            new_concerns.append(
                _CORP_KEY_CONCERN_REFRAME_ES if _lang(context) == "es"
                else _CORP_KEY_CONCERN_REFRAME_EN
            )
            changed = True
        else:
            new_concerns.append(concern)
    if changed:
        data = dict(data)
        data["key_concerns"] = new_concerns

    return data


# ── Rules 1, 4, 5: General text scrubbing ─────────────────────────────────────

def _apply_rules_1_4_5_scrub(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply score-attribution and attractiveness-link scrubbing to all narrative
    text fields in conclusion_data.

    Targets: score_rationale, summary, investment_thesis, data_limitations,
             dimension_scores[*].rationale, key_strengths, key_concerns,
             key_questions, next_steps, readiness.notes
    """
    changes: List[str] = []

    # Top-level string fields
    for field in ("score_rationale", "summary", "investment_thesis", "data_limitations"):
        original = data.get(field)
        if not original:
            continue
        fixed = _scrub_field(original)
        if fixed != original:
            data = dict(data)
            data[field] = fixed
            changes.append(field)

    # Dimension score rationales
    dims = data.get("dimension_scores")
    if dims:
        new_dims: Dict[str, Any] = {}
        dims_changed = False
        for dim_name, dim_val in dims.items():
            if not isinstance(dim_val, dict):
                new_dims[dim_name] = dim_val
                continue
            original = dim_val.get("rationale")
            fixed = _scrub_field(original)
            if fixed != original:
                new_dim = dict(dim_val)
                new_dim["rationale"] = fixed
                new_dims[dim_name] = new_dim
                dims_changed = True
                changes.append(f"dimension_scores.{dim_name}.rationale")
            else:
                new_dims[dim_name] = dim_val
        if dims_changed:
            data = dict(data)
            data["dimension_scores"] = new_dims

    # List fields
    for list_field in ("key_strengths", "key_concerns", "key_questions", "next_steps"):
        original = data.get(list_field)
        if not original:
            continue
        fixed = _scrub_list(original)
        if fixed != original:
            data = dict(data)
            data[list_field] = fixed
            changes.append(list_field)

    # Readiness notes
    readiness = data.get("readiness")
    if isinstance(readiness, dict):
        original_notes = readiness.get("notes")
        fixed_notes = _scrub_field(original_notes)
        if fixed_notes != original_notes:
            data = dict(data)
            data["readiness"] = dict(readiness)
            data["readiness"]["notes"] = fixed_notes
            changes.append("readiness.notes")

    if changes:
        logger.info(
            "[guardrails] Rules 1/4/5: Scrubbed score-attribution / attractiveness-link "
            "language in %d field(s): %s",
            len(changes), changes,
        )

    return data


# ── Executive-summary post-processing (Rule 6 extension) ─────────────────────

def scrub_executive_summary_text_fields(
    exec_summary_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply Rule 6 (and Rules 1/5) text scrubbing to executive_summary output fields.

    executive_summary has a different schema from conclusion_data, so it is not
    covered by apply_scoring_guardrails.  Call this after run_executive_summary
    returns to ensure the same framing guarantees apply to the report's first page.

    Targets:
      what_it_does    (str)
      investment_snapshot (list[str])
      key_risks       (list[str])
      final_verdict   (str)
    """
    # Validation kill switch: bypass all scrubbing (mode B experiment).
    if _calibration_disabled():
        logger.info("scrub_executive_summary_text_fields: BYPASSED (DISABLE_CALIBRATION=1)")
        return exec_summary_data or {}

    if not exec_summary_data:
        return exec_summary_data or {}

    data = dict(exec_summary_data)
    changed: List[str] = []

    # String fields
    for field in ("what_it_does", "final_verdict"):
        original = data.get(field)
        if not original:
            continue
        fixed = _scrub_field(original)
        if fixed != original:
            data[field] = fixed
            changed.append(field)

    # List fields
    for field in ("investment_snapshot", "key_risks"):
        original = data.get(field)
        if not original:
            continue
        fixed = _scrub_list(original)
        if fixed != original:
            data[field] = fixed
            changed.append(field)

    if changed:
        logger.info(
            "[guardrails] exec_summary scrub (Rules 1/5/6): fixed %d field(s): %s",
            len(changed), changed,
        )

    return data


# ── Main entry point ──────────────────────────────────────────────────────────

def apply_scoring_guardrails(
    conclusion_data: Dict[str, Any],
    management_data: Dict[str, Any],
    corporate_structure_data: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply deterministic post-processing guardrails to conclusion_data.

    Rules enforced:
      1. Remove language attributing score reduction to data absence.
      2. Fix management interpretation for established companies with no extracted executives.
      3. Fix corporate structure interpretation for entity_mapping_required.
      4. Ensure missing data does not cascade to negative score or label framing.
      5. Rewrite text explicitly linking data absence to lower business attractiveness.

    Parameters
    ----------
    conclusion_data          : Output of run_conclusion.
    management_data          : Output of run_management (read-only — used to check executives).
    corporate_structure_data : Output of run_corporate_structure (read-only — secondary check).
    context                  : Output of build_analysis_context from calibration.py.

    Returns
    -------
    Modified conclusion_data. All other inputs are unchanged.
    """
    # Validation kill switch: bypass all guardrails (mode B experiment).
    if _calibration_disabled():
        logger.info("apply_scoring_guardrails: BYPASSED (DISABLE_CALIBRATION=1)")
        return conclusion_data or {}

    if not conclusion_data:
        return conclusion_data or {}

    data: Dict[str, Any] = dict(conclusion_data)  # top-level copy

    is_established: bool = context.get("is_established_company", False)
    entity_status: str = context.get("entity_detection_status", "unknown")

    # Determine if executives were extracted (management_data is read-only here)
    executives = (management_data or {}).get("executives") or []
    no_executives: bool = not bool(executives)

    # ── Rule 2: Management fix ────────────────────────────────────────────────
    # Only applies when we know this is an established company AND executives
    # are absent from the extracted data (indicating pipeline limitation, not reality).
    if is_established and no_executives:
        data = _apply_rule_2_management(data, context)

    # ── Rule 3: Corporate structure fix ──────────────────────────────────────
    # Only applies when entity_mapping_required — the entity exists but was not
    # extracted from standard registries.
    if entity_status == "entity_mapping_required":
        data = _apply_rule_3_corporate_structure(data, context)

    # ── Rules 1, 4, 5: General text scrubbing ────────────────────────────────
    # Applied to all companies regardless of listing status.
    # Score-attribution and attractiveness-link language is wrong everywhere.
    data = _apply_rules_1_4_5_scrub(data)

    return data
