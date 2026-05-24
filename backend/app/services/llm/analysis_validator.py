"""
Second-pass analysis validator + corrector (OpenAI layer).

Receives the full assembled Gemini analysis and a summary of the source
materials, and returns a corrected version of the same structure.

This layer is conservative by design:
  - It REMOVES invalid sources and claims it cannot support.
  - It REWRITES contaminated text with cautious language.
  - It IMPROVES the management section when evidence is already present.
  - It FIXES cross-section contradictions.
  - It does NOT invent new facts.
  - It does NOT change programmatically-computed scores.

If OpenAI is unavailable or fails, it returns the original analysis unchanged
and logs a warning, so the pipeline never breaks because of this layer.
"""
import copy
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.llm_result import LLMResult
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Fields in conclusion that are programmatically computed after the LLM call.
# These are never sent to OpenAI and are always restored from the original.
_PROTECTED_CONCLUSION_FIELDS = ("overall_score", "priority_rating", "dimension_scores")

# Top-level keys the validator must return (matching the assembled analysis).
_EXPECTED_KEYS = [
    "classification",
    "business_model",
    "traction",
    "risks",
    "management",
    "competitive_position",
    "operational_signals",
    "corporate_structure",
    "conclusion",
    "references",
]

# ── Language-specific absolute rules ──────────────────────────────────────────

_LANG_RULES = {
    "es": (
        "REGLA ABSOLUTA DE IDIOMA: Todo el contenido textual del JSON de salida DEBE estar en español. "
        "Sin excepción. No mezcles inglés, francés ni ningún otro idioma con el español. "
        "Si el contenido recibido está en otro idioma, tradúcelo al español en tu respuesta."
    ),
    "en": (
        "ABSOLUTE LANGUAGE RULE: All textual content in the output JSON MUST be in English. "
        "No exceptions. Do not mix any other language with English. "
        "If received content is in another language, translate it to English in your response."
    ),
    "fr": (
        "RÈGLE DE LANGUE ABSOLUE: Tout le contenu textuel du JSON de sortie DOIT être en français. "
        "Sans exception. Ne mélangez aucune autre langue avec le français."
    ),
    "de": (
        "ABSOLUTE SPRACHREGEL: Alle Textinhalte im Ausgabe-JSON MÜSSEN auf Deutsch sein. "
        "Keine Ausnahmen. Keine Sprachmischung."
    ),
    "it": (
        "REGOLA DI LINGUA ASSOLUTA: Tutto il contenuto testuale nel JSON di output DEVE essere in italiano. "
        "Senza eccezioni. Non mischiare altre lingue con l'italiano."
    ),
}


def _build_system_prompt(language: str) -> str:
    lang = language or "es"
    lang_rule = _LANG_RULES.get(lang, _LANG_RULES["es"])

    return f"""You are a senior M&A analyst acting as a second-pass quality validator and editor.

You receive a structured company analysis produced by a first-pass AI model, together with a
summary of the actual source materials used. Your job is to validate and CORRECT the analysis.
Return the CORRECTED REPORT — not an audit memo, not a list of issues, but the actual fixed output.

{lang_rule}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLE AND OPERATING PRINCIPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Conservative: prefer deletion and softening over speculation.
• Evidence-driven: every retained claim must be traceable to the provided sources.
• Precise: changes must be grounded — do not rewrite sections that are accurate.
• Correction over commentary: output the fixed analysis, not a description of problems.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORRECTION RULES (apply in this order)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ENTITY MATCH VALIDATION
   For every traction signal, executive mention, news reference, corporate event,
   competitor mention, or external claim in the analysis:
   Ask: does this CLEARLY refer to the SAME company being analyzed?
   Evidence of same company: same domain, same sector/industry, same registered name,
   direct mention of the company in a context consistent with its known business.
   If the answer is NO or UNCERTAIN:
   → Remove it from its array/field.
   → Remove or rewrite any statement in other fields that depended on it.
   → Remove its entry from references.sources.
   The validator corrects contamination — it does not leave ambiguous sources in place.

2. EVIDENCE QUALITY CORRECTION
   If a claim is:
   • Not grounded in any provided source
   • Overstated relative to the available evidence
   • Contradicted by another section or by the sources summary
   • Based on a source that was removed in step 1
   Then: delete it, OR rewrite it with cautious language
   ("the available data suggests...", "it appears that...", "cannot be confirmed from public sources"),
   OR replace it with a weaker but supportable formulation.
   Never leave an unsupported strong claim intact.

3. HALLUCINATION PREVENTION
   You may ONLY: remove, rewrite (more cautious), soften, reorganize, or correct
   based on evidence ALREADY PRESENT in the analysis or source summary.
   You may NOT: invent new executives, new traction signals, new competitors,
   new corporate events, or any fact not already in the materials.

4. MANAGEMENT / LEADERSHIP IMPROVEMENT
   If management.executives is empty or management.leadership_analysis says
   "no executives identified", check whether:
   - Any names, roles, or titles appear elsewhere in the analysis
     (factual_profile.public_signals, traction signals, corporate_structure,
      corporate events, news articles, Wikipedia summary)
   - The source summary contains named individuals associated with the company
   If usable evidence of named executives exists: update executives array and
   leadership_analysis accordingly, with source="website" or the appropriate source.
   If no usable evidence exists: keep the uncertainty. Do NOT invent names.

5. SOURCE LIST CLEANING (references.sources)
   Keep:
   • All official company website pages
   • External sources where the article or record clearly matches the same company entity
     (same sector, domain referenced, or company name used in correct context)
   Remove:
   • Sources about a different company with the same name
   • Sources where the company name appears incidentally (not as the subject)
   • Sources that appear to be about unrelated entities (different sector, different geography)
   The clean source list must be what appears in the final PDF.

6. CROSS-SECTION CONSISTENCY
   Fix contradictions such as:
   • A section saying "no external signals" while traction has valid news articles
   • "leadership unknown" in conclusion while management has named executives
   • Strong confidence claims while evidence_profile shows sparse coverage
   • One section using invalid sources while another has already excluded them
   • Conclusion summary referencing traction signals that were removed as invalid
   All text sections must be internally coherent after corrections.

7. LANGUAGE CONSISTENCY
   Ensure every text field in the output is in the requested language.
   Translate any mixed-language content. Enum values (high/medium/low/etc.) stay as-is.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE CONSTRAINTS — DO NOT VIOLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• DO NOT change: conclusion.overall_score, conclusion.priority_rating,
  conclusion.dimension_scores — these are programmatically computed and protected.
• DO NOT add new top-level keys to any section.
• DO NOT remove required fields — set to null or [] instead of omitting them.
• DO NOT change the JSON schema or structure.
• DO NOT invent facts. Absence of evidence → express uncertainty, not fabrication.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — OUTPUT ONLY MODIFIED SECTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a valid JSON object containing ONLY the top-level sections you are modifying.
If a section needs NO changes, omit it entirely from your response.
The merge layer will preserve unchanged sections from the original.

Valid top-level keys (include only those you change):
classification, business_model, traction, risks, management,
competitive_position, operational_signals, corporate_structure,
conclusion, references

If you change nothing at all, return an empty JSON object: {{}}

No commentary outside the JSON. No markdown fences. Only the corrected JSON."""


def _build_sources_summary(
    normalized: Dict[str, Any],
    company_name: str,
    company_domain: str,
) -> str:
    """
    Builds a compact, readable summary of the source evidence actually available.
    This gives the validator context to verify entity matches without sending
    the full raw scraped data.
    """
    lines: List[str] = []

    lines.append(f"Company name: {company_name}")
    lines.append(f"Company domain: {company_domain or 'unknown'}")
    lines.append("")

    # Website pages
    pages = normalized.get("website_pages", [])
    if pages:
        lines.append(f"WEBSITE PAGES SCRAPED ({len(pages)}):")
        for p in pages[:15]:
            lines.append(f"  • {p.get('url', '')}  [{p.get('title', '')}]")
    else:
        lines.append("WEBSITE PAGES SCRAPED: none")
    lines.append("")

    # Corporate registry
    corp = normalized.get("corporate_data") or {}
    if corp.get("legal_name"):
        lines.append("CORPORATE REGISTRY DATA (verified facts):")
        lines.append(f"  Legal name: {corp.get('legal_name')}")
        lines.append(f"  Status: {corp.get('status')}")
        lines.append(f"  Jurisdiction: {corp.get('jurisdiction')}")
        lines.append(f"  Incorporation: {corp.get('incorporation_date')}")
        lines.append(f"  Type: {corp.get('company_type')}")
    else:
        lines.append("CORPORATE REGISTRY DATA: not available")
    lines.append("")

    # BORME
    borme = normalized.get("borme_entries", [])
    if borme:
        lines.append(f"BORME ENTRIES ({len(borme)}):")
        for b in borme[:5]:
            lines.append(f"  • {b.get('title', '')} ({b.get('date', '')})")
    else:
        lines.append("BORME ENTRIES: none")
    lines.append("")

    # Wikipedia
    wiki = normalized.get("wikipedia_summary")
    if wiki:
        summary_preview = (wiki.get("summary") or "")[:300]
        lines.append(f"WIKIPEDIA: {wiki.get('title')} — {summary_preview}...")
    else:
        lines.append("WIKIPEDIA: not found")
    lines.append("")

    # GDELT news
    gdelt_articles = normalized.get("news_articles", [])
    if gdelt_articles:
        lines.append(f"GDELT NEWS (pre-filtered, {len(gdelt_articles)} articles):")
        for a in gdelt_articles[:10]:
            lines.append(
                f"  • \"{a.get('title', '')}\" — {a.get('domain', '')} ({a.get('date', '')})"
            )
    else:
        lines.append("GDELT NEWS: no relevant articles found")
    lines.append("")

    # Google News
    gnews_articles = normalized.get("google_news_articles", [])
    if gnews_articles:
        lines.append(f"GOOGLE NEWS (pre-filtered, {len(gnews_articles)} articles):")
        for a in gnews_articles[:10]:
            lines.append(
                f"  • \"{a.get('title', '')}\" — {a.get('source_name', '')} ({a.get('date', '')})"
            )
    else:
        lines.append("GOOGLE NEWS: no relevant articles found")
    lines.append("")

    # Platform signals
    app_store = normalized.get("app_store_data")
    github = normalized.get("github_data")
    similarweb = normalized.get("similarweb_data")
    glassdoor = normalized.get("glassdoor_data")

    if app_store:
        lines.append(
            f"APP STORE: \"{app_store.get('name', '')}\" by {app_store.get('developer', '')} "
            f"— rating {app_store.get('rating', 'N/A')}, {app_store.get('review_count', 0)} reviews"
        )
    if github:
        lines.append(
            f"GITHUB: {github.get('login', '')} — {github.get('public_repos', 0)} repos, "
            f"{github.get('stars_total', 0)} total stars"
        )
    if similarweb:
        lines.append(
            f"SIMILARWEB: global rank #{similarweb.get('global_rank', 'N/A')}, "
            f"{similarweb.get('monthly_visits_estimate', 'N/A')} monthly visits, "
            f"category: {similarweb.get('category', 'N/A')}"
        )
    if glassdoor:
        lines.append(
            f"GLASSDOOR: {glassdoor.get('overall_rating', 'N/A')}/5 "
            f"({glassdoor.get('review_count', 0)} reviews), "
            f"{glassdoor.get('recommend_pct', 'N/A')}% recommend"
        )

    if not any([app_store, github, similarweb, glassdoor]):
        lines.append("PLATFORM DATA (GitHub/App Store/SimilarWeb/Glassdoor): none found")
    lines.append("")

    # Data quality warnings (what was discarded)
    warnings = normalized.get("data_quality_warnings", [])
    if warnings:
        lines.append(f"DATA QUALITY WARNINGS ({len(warnings)} items discarded at scraping stage):")
        for w in warnings[:5]:
            lines.append(f"  ⚠ {w}")
        lines.append("")

    # Current references list
    refs = (normalized.get("references") or {}).get("sources", [])
    if refs:
        lines.append(f"CURRENT REFERENCES LIST ({len(refs)} entries):")
        for r in refs[:20]:
            lines.append(f"  • [{r.get('source_type', '')}] {r.get('title', '')} — {r.get('url', '')}")
    else:
        lines.append("CURRENT REFERENCES LIST: empty")

    return "\n".join(lines)


def _assemble_analysis_bundle(
    classification: Dict[str, Any],
    business_model: Dict[str, Any],
    traction: Dict[str, Any],
    risks: Dict[str, Any],
    management: Dict[str, Any],
    competitive_position: Dict[str, Any],
    operational_signals: Dict[str, Any],
    corporate_structure: Dict[str, Any],
    conclusion: Dict[str, Any],
    references: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Assembles all module outputs into the single dict sent to the validator.
    Uses deep copies to avoid mutating the originals.
    """
    return {
        "classification": copy.deepcopy(classification),
        "business_model": copy.deepcopy(business_model),
        "traction": copy.deepcopy(traction),
        "risks": copy.deepcopy(risks),
        "management": copy.deepcopy(management),
        "competitive_position": copy.deepcopy(competitive_position),
        "operational_signals": copy.deepcopy(operational_signals),
        "corporate_structure": copy.deepcopy(corporate_structure),
        "conclusion": copy.deepcopy(conclusion),
        "references": copy.deepcopy(references),
    }


def _restore_protected_fields(
    corrected: Dict[str, Any],
    original_conclusion: Dict[str, Any],
) -> None:
    """
    Overwrites protected conclusion fields with their original (programmatically
    computed) values, regardless of what the validator returned.

    This guarantees scoring integrity even if the model accidentally changes a score.
    Modifies corrected["conclusion"] in place.
    """
    if "conclusion" not in corrected:
        corrected["conclusion"] = {}
    for field in _PROTECTED_CONCLUSION_FIELDS:
        if field in original_conclusion:
            corrected["conclusion"][field] = original_conclusion[field]


def _safe_merge(
    corrected: Dict[str, Any],
    original: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merges a potentially incomplete corrected dict with the original.

    For each expected top-level key:
    - If corrected has it as a non-empty dict/list → use corrected
    - Otherwise → fall back to original

    This protects against OpenAI omitting a section entirely.
    """
    merged: Dict[str, Any] = {}
    for key in _EXPECTED_KEYS:
        corrected_val = corrected.get(key)
        original_val = original.get(key)

        if corrected_val and isinstance(corrected_val, (dict, list)):
            merged[key] = corrected_val
        elif corrected_val is not None:
            # Non-empty non-dict/list value (string, bool, etc.)
            merged[key] = corrected_val
        else:
            # Missing or null — fall back to original.
            # NOTE: omission is now intentional (validator returns only changed sections).
            # Log at debug, not warning.
            if key not in corrected:
                logger.debug(
                    f"Validator omitted key '{key}' (unchanged) — preserving original."
                )
            merged[key] = original_val

    return merged


async def validate_analysis(
    classification: Dict[str, Any],
    business_model: Dict[str, Any],
    traction: Dict[str, Any],
    risks: Dict[str, Any],
    management: Dict[str, Any],
    competitive_position: Dict[str, Any],
    operational_signals: Dict[str, Any],
    corporate_structure: Dict[str, Any],
    conclusion: Dict[str, Any],
    normalized: Dict[str, Any],
    company_name: str,
    company_domain: str,
    language: str = "es",
    analysis_id: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Second-pass analysis validator + corrector.

    Passes the full assembled analysis to OpenAI for validation and correction.
    Returns a corrected version of the same structure.

    Graceful degradation:
    - If OPENAI_API_KEY is not configured → returns originals unchanged, logs warning.
    - If OpenAI call fails → returns originals unchanged, logs error.
    - If response is missing keys → merges with originals for the missing sections.
    - Protected conclusion fields are always restored from originals.
    """
    # ── Guard: skip if no OpenAI key ─────────────────────────────────────────
    if not settings.openai_api_key:
        logger.info(
            "OpenAI validation skipped: OPENAI_API_KEY not configured. "
            "Set OPENAI_API_KEY in .env to enable the second-pass validator."
        )
        return _assemble_analysis_bundle(
            classification, business_model, traction, risks, management,
            competitive_position, operational_signals, corporate_structure,
            conclusion, normalized.get("references", {}),
        )

    # ── Assemble original bundle (used for fallback + protected field restore) ──
    original_references = normalized.get("references", {})
    original_bundle = _assemble_analysis_bundle(
        classification, business_model, traction, risks, management,
        competitive_position, operational_signals, corporate_structure,
        conclusion, original_references,
    )

    # ── Build sources summary ─────────────────────────────────────────────────
    sources_summary = _build_sources_summary(normalized, company_name, company_domain)

    # ── Build prompts ─────────────────────────────────────────────────────────
    system_prompt = _build_system_prompt(language)

    # Serialize analysis — indent=2 makes it readable for the model
    analysis_json = json.dumps(original_bundle, ensure_ascii=False, indent=2)

    user_prompt = (
        f"=== COMPANY IDENTITY ===\n"
        f"Name: {company_name}\n"
        f"Domain: {company_domain or 'unknown'}\n"
        f"Analysis language: {language}\n\n"
        f"=== SOURCE MATERIALS AVAILABLE ===\n"
        f"{sources_summary}\n\n"
        f"=== ANALYSIS TO VALIDATE AND CORRECT ===\n"
        f"{analysis_json}\n\n"
        f"Validate and correct the analysis above following the rules in your system prompt. "
        f"Return a JSON object containing ONLY the top-level sections you modify. "
        f"Omit unchanged sections entirely. Return {{}} if nothing needs changing."
    )

    # ── Call OpenAI ───────────────────────────────────────────────────────────
    try:
        from app.services.llm.openai_client import openai_client  # noqa: PLC0415

        logger.info(
            f"Starting OpenAI second-pass validation for '{company_name}' "
            f"(analysis_json={len(analysis_json)} chars, "
            f"sources_summary={len(sources_summary)} chars)"
        )

        result = await openai_client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_keys=_EXPECTED_KEYS,
            temperature=0.1,
            max_output_tokens=16_384,
        )

        corrected_raw: Dict[str, Any] = result["data"]
        duration_ms: int = result["duration_ms"]

        logger.info(
            f"OpenAI validation completed in {duration_ms}ms for '{company_name}'"
        )

    except Exception as exc:
        logger.error(
            f"OpenAI validation failed for '{company_name}': {exc}. "
            f"Returning original analysis in degraded mode.",
            exc_info=True,
        )
        # Return original with a degraded marker so the orchestrator can
        # distinguish validated analyses from unvalidated ones.
        return {**original_bundle, "_validation_degraded": True}

    # ── Merge corrected with originals (protects against omissions) ──────────
    corrected = _safe_merge(corrected_raw, original_bundle)

    # ── Restore programmatically-computed conclusion fields ───────────────────
    _restore_protected_fields(corrected, conclusion)

    # ── Persist audit record ──────────────────────────────────────────────────
    if analysis_id and db:
        try:
            # Build a diff summary for the audit record (what changed at top level)
            changes_summary = {}
            for key in _EXPECTED_KEYS:
                orig_json = json.dumps(original_bundle.get(key), ensure_ascii=False, sort_keys=True)
                corr_json = json.dumps(corrected.get(key), ensure_ascii=False, sort_keys=True)
                if orig_json != corr_json:
                    changes_summary[key] = "modified"
                else:
                    changes_summary[key] = "unchanged"

            record = LLMResult(
                analysis_id=analysis_id,
                module_name="analysis_validator",
                input_payload={
                    "company_name": company_name,
                    "company_domain": company_domain,
                    "language": language,
                    "analysis_chars": len(analysis_json),
                    "sources_summary_chars": len(sources_summary),
                    "sections_sent": _EXPECTED_KEYS,
                },
                output_payload={
                    "sections_changed": changes_summary,
                    "duration_ms": duration_ms,
                    "model": settings.openai_model,
                },
                model_used=settings.openai_model,
                duration_ms=duration_ms,
            )
            db.add(record)
            await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to persist validator audit record: {exc}")

    return corrected
