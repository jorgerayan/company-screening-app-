"""
Centralized deterministic calibration layer.

Builds a shared analysis_context from structured inputs (no LLM calls)
and provides post-processing filters that enforce calibration rules on
LLM outputs regardless of prompt compliance.

This is the authoritative layer for:
  · listing_status interpretation
  · entity_detection_status inference
  · data-gap risk filtering (public vs private behaviour)
  · executive-summary key_risk hygiene
  · output validation and warning logging

All functions are deterministic (rule-based). No LLM calls.
"""
from __future__ import annotations

import os
from typing import Any, Dict, FrozenSet, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Validation kill switch ────────────────────────────────────────────────────
# When DISABLE_CALIBRATION=1, the public filter functions return their inputs
# unchanged. Used exclusively for validation experiments (mode B in chapter 6
# of the TFG memoria). Has no effect when unset or set to "0".
def _calibration_disabled() -> bool:
    return os.getenv("DISABLE_CALIBRATION", "0") == "1"


# ── Constants ─────────────────────────────────────────────────────────────────

# Risk categories that exclusively indicate data-absence risks
_DATA_GAP_CATEGORIES: FrozenSet[str] = frozenset({
    "opacity",
    "financial_visibility",
})

# Tokens that strongly indicate a data-gap risk when found in the risk name.
# Intentionally phrase-specific to avoid false-positives on substantive risks
# that happen to share a word (e.g. "regulatory disclosure obligations" is NOT a data-gap risk).
# Primary detection relies on risk_category; these are fallback for mis-classified entries.
# (case-insensitive substring match)
_DATA_GAP_NAME_TOKENS: FrozenSet[str] = frozenset({
    "financial visibility",
    "financial opacity",
    "limited disclosure",
    "limited financial",
    "limited public disclosure",
    "lack of financial transparency",
    "missing financial",
    "no financial data",
    "financial data absence",
    "financial data not",
    "financial performance not publicly",
    "unit economics not publicly",
    "financial information not available",
    "public financial disclosure",
})

# Language that must never appear in key_risks for normal private-company data absence
_FORBIDDEN_KEY_RISK_TERMS: tuple = (
    "critical opacity",
    "impossible to value",
    "severe lack of transparency",
    "major financial red flag",
    "total lack of financial visibility",
    "valuation cannot proceed",
    "critical informational gap",
)

# Structural types that constitute a confirmed non-acquirable entity
_NON_ACQUIRABLE_STRUCT_TYPES: FrozenSet[str] = frozenset({
    "network_firm", "partnership_llp", "nonprofit_guarantee", "consortium",
})

# Canonical note injected into risks.notes when a public company generates data-gap risks
_PUBLIC_PIPELINE_NOTE = (
    "Financial data not extracted from public sources — pipeline limitation. "
    "Mandatory periodic disclosures exist but were not retrieved by the current "
    "scraping pass."
)

# Canonical key_risk replacement for private companies using forbidden language
_CANONICAL_PRIVATE_DISCLOSURE_KEY_RISK = (
    "Financial performance and unit economics require validation in due diligence "
    "— not independently verified from public sources."
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_data_gap_risk(risk: Dict[str, Any]) -> bool:
    """Return True if this risk entry is primarily about data absence / limited disclosure."""
    # Primary check: structured risk_category field
    if risk.get("risk_category") in _DATA_GAP_CATEGORIES:
        return True
    # Secondary check: scan the risk name for data-gap tokens (case-insensitive)
    name = (risk.get("name") or "").lower()
    return any(tok in name for tok in _DATA_GAP_NAME_TOKENS)


def _is_data_gap_text(text: str) -> bool:
    """Return True if a free-text string (key_risk bullet) is about data absence."""
    t = text.lower()
    return any(tok in t for tok in _DATA_GAP_NAME_TOKENS)


def _has_forbidden_language(text: str) -> bool:
    """Return True if text contains any phrase forbidden for normal private-company absence."""
    t = text.lower()
    return any(f in t for f in _FORBIDDEN_KEY_RISK_TERMS)


def _pipeline_note(existing: Optional[str]) -> str:
    """Produce the canonical pipeline-limitation note, appending to any existing notes."""
    if existing:
        return f"{existing.rstrip('.')}. {_PUBLIC_PIPELINE_NOTE}"
    return _PUBLIC_PIPELINE_NOTE


def _has_explicit_negative_evidence(risk: Dict[str, Any]) -> bool:
    """
    Return True if the risk entry contains explicit negative evidence (fraud, insolvency,
    contradiction, etc.) that would justify HIGH severity for a data-gap risk.
    """
    evidence_text = (risk.get("evidence") or "").lower()
    explanation_text = (risk.get("explanation") or "").lower()
    combined = f"{evidence_text} {explanation_text}"
    negative_terms = (
        "fraud", "insolvency", "bankrupt", "sanction", "regulatory action",
        "enforcement", "penalty", "contradiction", "contradicts", "implausible",
        "false claim", "misrepresentation", "administrative penalty",
    )
    return any(term in combined for term in negative_terms)


_CONSOLIDATED_DISCLOSURE_NAMES: Dict[str, str] = {
    "es": "Divulgación financiera pública limitada — validación requerida en due diligence",
    "en": "Limited public financial disclosure — validation required in due diligence",
    "fr": "Divulgation financière publique limitée — validation requise en due diligence",
    "de": "Begrenzte öffentliche Finanzoffenlegung — Validierung in der Due Diligence erforderlich",
    "it": "Divulgazione finanziaria pubblica limitata — convalida richiesta nella due diligence",
}


def _build_consolidated_disclosure_risk(
    data_gap_risks: List[Dict[str, Any]],
    language: str = "es",
) -> Dict[str, Any]:
    """
    Merge multiple data-gap risks into a single consolidated MEDIUM disclosure risk.
    Uses the first risk as the structural template; combines evidence points.
    """
    base = data_gap_risks[0]
    combined_evidence: List[str] = []
    for r in data_gap_risks:
        evidence = (r.get("evidence") or "").strip()
        if evidence and evidence not in combined_evidence:
            combined_evidence.append(evidence)

    _lang_key = (language or "es").lower()[:2]
    _name = _CONSOLIDATED_DISCLOSURE_NAMES.get(_lang_key, _CONSOLIDATED_DISCLOSURE_NAMES["en"])

    return {
        "name": _name,
        "severity": "medium",
        "risk_category": "financial_visibility",
        "evidence": " ".join(combined_evidence[:3]) or (base.get("evidence") or ""),
        "explanation": (
            base.get("explanation")
            or (
                "This private or startup company does not publish internal operating metrics "
                "(ARR, EBITDA, gross margin, churn, unit economics) through public channels. "
                "This is the expected norm for companies at this stage and does not constitute "
                "a red flag or sign of opacity. The financial picture requires validation "
                "through direct access to internal accounts during due diligence. Public sources "
                "do not allow margin or retention analysis. Valuation would require access to "
                "internal financials. This is a verification step, not a barrier to interest."
            )
        ),
        "what_to_validate": (
            base.get("what_to_validate")
            or (
                "1. Request management accounts and last 2–3 years of audited financials. "
                "2. Review unit economics: CAC, LTV, churn, gross margin. "
                "3. Validate ARR/MRR growth trajectory against bank statements or auditor sign-off."
            )
        ),
        "evidence_type": "reasonable_inference",
    }


# ── Context builder ───────────────────────────────────────────────────────────

def build_analysis_context(
    classification: Dict[str, Any],
    normalized_data: Dict[str, Any],
    corporate_structure: Optional[Dict[str, Any]] = None,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Build a shared, deterministic analysis context from classification output
    and normalised scraped data.

    Call once after run_classifier and again after run_corporate_structure
    (passing corp_structure on the second call) to get the most complete context.

    Returns
    -------
    Dict with fields:
      listing_status                        str
      is_public_company                     bool
      is_private_or_startup                 bool
      entity_detection_status               str
      is_established_company                bool
      coverage_tier                         str
      has_any_external                      bool
      has_legal_data                        bool
      financial_data_absence_interpretation str
      management_absence_interpretation     str
      registry_absence_interpretation       str
      digital_data_absence_interpretation   str
      _struct_type                          str  (internal — for downstream use)
      _group_acquirable                     bool|None
      _evidence_profile                     dict
    """
    # ── Listing status ────────────────────────────────────────────────────────
    listing_status = (classification.get("listing_status") or "unknown").lower()
    is_public_company = listing_status == "public"
    is_private_or_startup = listing_status in ("private", "startup", "subsidiary")

    # ── Evidence profile ──────────────────────────────────────────────────────
    norm = normalized_data or {}
    evidence_profile: Dict[str, Any] = norm.get("evidence_profile") or {}
    coverage_tier: str = evidence_profile.get("coverage_tier", "sparse")
    _tier_rich = coverage_tier == "rich"
    _tier_moderate = coverage_tier == "moderate"

    news_count: int = evidence_profile.get("news_article_count", 0)
    has_external_news: bool = news_count >= 1
    has_non_news_external: bool = evidence_profile.get("has_any_external_non_news", False)
    has_any_external: bool = has_external_news or has_non_news_external

    # ── Legal / registry data ─────────────────────────────────────────────────
    has_legal_data: bool = (
        bool((norm.get("corporate_data") or {}).get("legal_name"))
        or bool(norm.get("borme_entries"))
        or bool(
            classification.get("factual_profile", {})
            .get("corporate_data", {})
            .get("legal_name")
        )
        or _tier_rich
        or (_tier_moderate and evidence_profile.get("has_corporate_registry", False))
    )

    # ── Established company ───────────────────────────────────────────────────
    geography = classification.get("geography") or []
    geo_count: int = len(geography) if isinstance(geography, list) else 0
    is_established_company: bool = (
        is_public_company                                 # public companies are definitionally established
        or evidence_profile.get("is_high_visibility", False)
        or coverage_tier == "rich"
        or (geo_count >= 2 and has_external_news)
        or (geo_count >= 3 and has_non_news_external)
        or (has_external_news and has_non_news_external)
    )

    # ── Corporate structure signals ───────────────────────────────────────────
    corp = corporate_structure or {}
    acq_assessment: Dict[str, Any] = corp.get("acquirability_assessment") or {}
    struct_type: str = acq_assessment.get("structure_type", "unknown")
    group_acquirable = acq_assessment.get("group_level_acquirable")  # bool | None

    # ── Entity detection status ───────────────────────────────────────────────
    if group_acquirable is False and struct_type in _NON_ACQUIRABLE_STRUCT_TYPES:
        entity_detection_status = "structurally_non_acquirable"
    elif has_legal_data:
        entity_detection_status = "verified_entity"
    elif is_private_or_startup or is_established_company or has_any_external:
        entity_detection_status = "entity_mapping_required"
    else:
        entity_detection_status = "unknown"

    # ── Interpretation strings ────────────────────────────────────────────────
    if is_public_company:
        financial_interp = (
            "Public company — mandatory periodic disclosures legally required. "
            "Missing financial data = pipeline/scraping limitation, NOT business opacity. "
            "Do NOT generate a financial-disclosure risk entry. Do NOT penalise transparency."
        )
        management_interp = (
            "Public company — executive disclosures mandated by securities regulations. "
            "Missing names = extraction gap, NOT leadership absence. "
            "Do NOT frame as key-person risk or leadership opacity."
        )
        registry_interp = (
            "Public company — statutory filings confirm entity existence. "
            "Missing registry data = scraping limitation only. "
            "Do NOT treat as structural barrier or opacity signal."
        )
        digital_interp = (
            "Public company — web/app/social data absence = scraping limitation. "
            "Do NOT infer low digital presence from extraction gaps."
        )
    elif entity_detection_status == "structurally_non_acquirable":
        financial_interp = (
            "Structurally non-acquirable entity (network/partnership/consortium). "
            "Financial data absence is secondary to the structural transaction barrier. "
            "Focus analysis on carve-out or individual entity opportunities."
        )
        management_interp = (
            "Structurally non-acquirable entity — management analysis should focus "
            "on individual entity/division leadership, not group-level."
        )
        registry_interp = (
            "Structurally non-acquirable entity — group registry data is secondary. "
            "Individual entity registry data matters for carve-out analysis."
        )
        digital_interp = (
            "Structurally non-acquirable entity — individual entity digital footprint "
            "matters more than group-level digital presence for carve-out valuation."
        )
    elif is_private_or_startup:
        financial_interp = (
            "Private/startup company — ARR, EBITDA, margins, churn, cap table = "
            "expected limited public disclosure, NOT a red flag or sign of opacity. "
            "Financial absences belong in due diligence questions, not as high-severity risks. "
            "Maximum ONE consolidated MEDIUM disclosure risk; never HIGH for mere absence."
        )
        management_interp = (
            "Private/startup company — executive names may not be publicly disclosed. "
            "Absence of named executives is normal; do NOT frame as key-person risk "
            "or leadership opacity without additional corroborating evidence."
        )
        registry_interp = (
            "Private/startup company — OpenCorporates/BORME match failure = pipeline "
            "limitation, NOT proof that the legal entity does not exist. "
            "The company almost certainly has a registered entity — it was not extracted."
        )
        digital_interp = (
            "Private/startup company — SimilarWeb, app store, GitHub data may be absent "
            "for early-stage or niche companies. Absence is a limited digital footprint "
            "signal, not necessarily a business weakness."
        )
    else:
        # Unknown listing status — cautious neutral framing
        financial_interp = (
            "Listing status unknown — apply cautious inference. "
            "Missing financial data reduces confidence only, not scores."
        )
        management_interp = (
            "Listing status unknown — executive absence reduces management evidence quality "
            "but is not a direct score penalty."
        )
        registry_interp = (
            "Listing status unknown — registry absence reduces legal_entity readiness "
            "to medium but does not confirm non-existence."
        )
        digital_interp = (
            "Listing status unknown — digital data absence is a confidence reducer. "
            "Do not infer business weakness from scraping limitations."
        )

    return {
        "listing_status": listing_status,
        "is_public_company": is_public_company,
        "is_private_or_startup": is_private_or_startup,
        "entity_detection_status": entity_detection_status,
        "is_established_company": is_established_company,
        "coverage_tier": coverage_tier,
        "has_any_external": has_any_external,
        "has_legal_data": has_legal_data,
        "financial_data_absence_interpretation": financial_interp,
        "management_absence_interpretation": management_interp,
        "registry_absence_interpretation": registry_interp,
        "digital_data_absence_interpretation": digital_interp,
        # Output language — used by post-processing layers that emit canonical text
        "language": (language or "es").lower(),
        # Internal fields passed through for downstream use
        "_struct_type": struct_type,
        "_group_acquirable": group_acquirable,
        "_evidence_profile": evidence_profile,
    }


# ── Risk filter ───────────────────────────────────────────────────────────────

def apply_risk_filter(
    risks_data: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic post-processing filter for run_risks output.

    PUBLIC companies:
      · Remove ALL data-gap risks from the risks array.
      · Append the canonical pipeline-limitation note to the notes field.
      · Log a warning for every removed risk.

    PRIVATE / STARTUP companies:
      · If >1 data-gap risk exists, consolidate into one MEDIUM disclosure risk.
      · If exactly 1 data-gap risk exists and it is HIGH, downgrade to MEDIUM
        unless there is explicit negative evidence (fraud, insolvency, contradiction).
      · Log whenever consolidation or downgrade is performed.

    Substantive risks (competition, regulation, operational, etc.) are never touched.
    """
    # Validation kill switch: bypass all filtering (mode B experiment).
    if _calibration_disabled():
        logger.info("apply_risk_filter: BYPASSED (DISABLE_CALIBRATION=1)")
        return risks_data

    risks_data = dict(risks_data)  # shallow copy — do not mutate caller's dict
    risk_list: List[Dict[str, Any]] = list(risks_data.get("risks") or [])
    current_notes: Optional[str] = risks_data.get("notes")

    is_public: bool = context.get("is_public_company", False)
    is_private: bool = context.get("is_private_or_startup", False)

    data_gap_risks = [r for r in risk_list if _is_data_gap_risk(r)]
    substantive_risks = [r for r in risk_list if not _is_data_gap_risk(r)]

    if not data_gap_risks:
        return risks_data  # Nothing to filter

    if is_public:
        removed_names = [r.get("name", "unnamed") for r in data_gap_risks]
        logger.warning(
            "[calibration] PUBLIC COMPANY — removing %d data-gap risk(s) from risks array "
            "and routing to notes field: %s",
            len(data_gap_risks), removed_names,
        )
        risks_data["risks"] = substantive_risks
        risks_data["notes"] = _pipeline_note(current_notes)

    elif is_private:
        if len(data_gap_risks) > 1:
            logger.warning(
                "[calibration] PRIVATE/STARTUP — consolidating %d data-gap risks into "
                "one MEDIUM disclosure risk.",
                len(data_gap_risks),
            )
            consolidated = _build_consolidated_disclosure_risk(
                data_gap_risks,
                language=context.get("language", "es"),
            )
            risks_data["risks"] = substantive_risks + [consolidated]

        else:
            # Exactly one data-gap risk — check severity
            single = data_gap_risks[0]
            if single.get("severity") == "high" and not _has_explicit_negative_evidence(single):
                logger.warning(
                    "[calibration] PRIVATE/STARTUP — downgrading data-gap risk '%s' "
                    "from HIGH to MEDIUM (no explicit negative evidence).",
                    single.get("name"),
                )
                single = dict(single)
                single["severity"] = "medium"
                data_gap_risks = [single]
            risks_data["risks"] = substantive_risks + data_gap_risks

    return risks_data


# ── Executive summary risk filter ─────────────────────────────────────────────

def apply_executive_summary_risk_filter(
    exec_data: Dict[str, Any],
    context: Dict[str, Any],
    risks_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Post-processing filter for the executive summary key_risks field.

    · PUBLIC companies: remove any key_risk bullet that is about data absence.
    · PRIVATE companies: replace any bullet containing forbidden language with
      the canonical private-disclosure phrase.
    · Backfill from substantive risks if removal leaves fewer than 3 items.
    · Always trim to exactly 3 items.
    """
    # Validation kill switch: bypass all filtering (mode B experiment).
    if _calibration_disabled():
        logger.info("apply_executive_summary_risk_filter: BYPASSED (DISABLE_CALIBRATION=1)")
        return exec_data

    exec_data = dict(exec_data)
    key_risks: List[str] = list(exec_data.get("key_risks") or [])

    is_public: bool = context.get("is_public_company", False)
    is_private: bool = context.get("is_private_or_startup", False)

    filtered: List[str] = []

    for kr in key_risks:
        if is_public and _is_data_gap_text(kr):
            logger.warning(
                "[calibration] PUBLIC COMPANY — removing data-gap key_risk from "
                "executive summary: '%.80s'", kr,
            )
            continue  # drop entirely for public companies
        elif is_private and _has_forbidden_language(kr):
            logger.warning(
                "[calibration] PRIVATE/STARTUP — replacing forbidden-language key_risk "
                "in executive summary: '%.80s'", kr,
            )
            filtered.append(_CANONICAL_PRIVATE_DISCLOSURE_KEY_RISK)
        else:
            filtered.append(kr)

    # Backfill from substantive risks if we are below 3 items
    if len(filtered) < 3:
        all_risks: List[Dict[str, Any]] = risks_data.get("risks") or []
        substantive = [
            r for r in all_risks
            if not _is_data_gap_risk(r)
            and r.get("severity") in ("high", "medium")
        ]
        # High severity first, then medium
        substantive.sort(key=lambda r: 0 if r.get("severity") == "high" else 1)

        existing_names = {
            item.split(":")[0].lower().strip()
            for item in filtered
        }
        for r in substantive:
            if len(filtered) >= 3:
                break
            r_name = (r.get("name") or "").lower().strip()
            if r_name not in existing_names:
                explanation_snippet = (r.get("explanation") or "")[:150]
                filtered.append(f"{r.get('name', '')}: {explanation_snippet}")
                existing_names.add(r_name)

    # Trim to exactly 3
    exec_data["key_risks"] = filtered[:3]
    return exec_data


# ── Output validation ─────────────────────────────────────────────────────────

def validate_outputs(
    context: Dict[str, Any],
    risks_data: Dict[str, Any],
    exec_data: Dict[str, Any],
    analysis_id: str,
) -> None:
    """
    Audit-only function: log warnings/errors for calibration violations that
    slipped through the post-processing filters. Does NOT modify any data.
    """
    # Validation kill switch: skip auditing (mode B experiment).
    if _calibration_disabled():
        logger.info("validate_outputs: BYPASSED (DISABLE_CALIBRATION=1)")
        return

    is_public: bool = context.get("is_public_company", False)
    is_private: bool = context.get("is_private_or_startup", False)
    entity_status: str = context.get("entity_detection_status", "unknown")

    risk_list: List[Dict[str, Any]] = risks_data.get("risks") or []
    key_risks: List[str] = exec_data.get("key_risks") or []

    # 1. Public company still has data-gap risks after filter
    if is_public:
        remaining_gaps = [r for r in risk_list if _is_data_gap_risk(r)]
        if remaining_gaps:
            logger.error(
                "[calibration:%s] VIOLATION — public company has %d data-gap risk(s) "
                "in final output after filter: %s",
                analysis_id, len(remaining_gaps),
                [r.get("name") for r in remaining_gaps],
            )

    # 2. Private company has multiple data-gap risks after filter
    if is_private:
        gap_risks = [r for r in risk_list if _is_data_gap_risk(r)]
        if len(gap_risks) > 1:
            logger.error(
                "[calibration:%s] VIOLATION — private/startup has %d data-gap risks "
                "after filter (expected ≤ 1): %s",
                analysis_id, len(gap_risks),
                [r.get("name") for r in gap_risks],
            )
        # Warn on unjustified HIGH severity
        for r in gap_risks:
            if r.get("severity") == "high" and not _has_explicit_negative_evidence(r):
                logger.warning(
                    "[calibration:%s] WARNING — private/startup data-gap risk '%s' is "
                    "HIGH severity without explicit negative evidence.",
                    analysis_id, r.get("name"),
                )

    # 3. Forbidden language in key_risks bullets
    for kr in key_risks:
        for forbidden in _FORBIDDEN_KEY_RISK_TERMS:
            if forbidden in kr.lower():
                logger.error(
                    "[calibration:%s] VIOLATION — forbidden language in key_risks: "
                    "'%s' found in '%.100s'",
                    analysis_id, forbidden, kr,
                )

    # 4. Non-acquirable label used for non-structurally-non-acquirable entity
    final_verdict = (exec_data.get("final_verdict") or "").lower()
    if (
        "estructura no adquirible" in final_verdict
        and entity_status != "structurally_non_acquirable"
    ):
        logger.error(
            "[calibration:%s] VIOLATION — 'Estructura no adquirible' in final_verdict "
            "but entity_detection_status = '%s'.",
            analysis_id, entity_status,
        )

    # 5. key_risks count sanity check
    if len(key_risks) < 3:
        logger.warning(
            "[calibration:%s] WARNING — key_risks has %d items (expected 3). "
            "Backfill may have failed.",
            analysis_id, len(key_risks),
        )

    logger.info(
        "[calibration:%s] Validation complete — listing_status=%s, "
        "entity_detection_status=%s, risks=%d, key_risks=%d.",
        analysis_id,
        context.get("listing_status"),
        entity_status,
        len(risk_list),
        len(key_risks),
    )
