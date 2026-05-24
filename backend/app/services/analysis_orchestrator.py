"""
Pipeline orchestrator — coordinates scraping → normalization → LLM modules → report.
Each step updates analysis.pipeline_step for frontend polling.
On partial failures, pipeline continues with available data.
"""
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.models.analysis import Analysis, AnalysisStatus
from app.models.company import Company
from app.models.report import Report, PriorityRating
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _calibration_disabled() -> bool:
    """Validation kill switch — returns True when DISABLE_CALIBRATION=1 in env/config."""
    from app.config import settings  # noqa: PLC0415 — avoid circular import at module level
    if settings.disable_calibration:
        logger.warning("Calibration BYPASSED (DISABLE_CALIBRATION=1) — mode B active")
        return True
    return False

PIPELINE_STEPS = [
    "scraping_website",
    "scraping_external_sources",
    "normalizing_data",
    "llm_classifier",
    "llm_business_model",
    "llm_traction",
    "llm_risks",
    "llm_management",
    "llm_competitive_position",
    "llm_operational_signals",
    "llm_corporate_structure",
    "llm_conclusion",
    "validating_analysis",   # OpenAI second-pass validator + corrector
    "llm_executive_summary", # Investor-grade executive summary (first page)
    "building_report",
]


async def _update_step(analysis: Analysis, step: str, db) -> None:
    analysis.pipeline_step = step
    await db.commit()


async def run_analysis_pipeline(analysis_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            analysis = await db.get(Analysis, analysis_id)
            if not analysis:
                logger.error(f"Analysis {analysis_id} not found")
                return

            company = await db.get(Company, analysis.company_id)
            language = company.language or "es"

            # Extract bare domain from website URL for relevance filtering
            _url = (company.website_url or "").lower()
            for _pfx in ("https://", "http://", "www."):
                if _url.startswith(_pfx):
                    _url = _url[len(_pfx):]
            company_domain = _url.split("/")[0].strip()

            analysis.status = AnalysisStatus.RUNNING
            analysis.started_at = datetime.now(timezone.utc)
            await db.commit()

            collected_data = {}

            # ── STEP 1: Scrape website ─────────────────────────────────────
            await _update_step(analysis, "scraping_website", db)
            try:
                from app.services.scrapers.website_scraper import scrape_website
                website_data = await scrape_website(
                    company.website_url, str(analysis.id), db
                )
                collected_data["website"] = website_data
            except Exception as e:
                logger.warning(f"Website scrape failed: {e}")
                collected_data["website"] = None

            # ── STEP 2: External sources ───────────────────────────────────
            await _update_step(analysis, "scraping_external_sources", db)

            try:
                from app.services.scrapers.opencorporates import fetch_opencorporates
                collected_data["opencorporates"] = await fetch_opencorporates(
                    company.name, company.country, str(analysis.id), db
                )
            except Exception as e:
                logger.warning(f"OpenCorporates failed: {e}")
                collected_data["opencorporates"] = None

            try:
                from app.services.scrapers.gdelt import fetch_gdelt_news
                collected_data["gdelt"] = await fetch_gdelt_news(
                    company.name, str(analysis.id), db
                )
            except Exception as e:
                logger.warning(f"GDELT failed: {e}")
                collected_data["gdelt"] = None

            try:
                from app.services.scrapers.borme import fetch_borme
                collected_data["borme"] = await fetch_borme(
                    company.name, company.country, str(analysis.id), db
                )
            except Exception as e:
                logger.warning(f"BORME failed: {e}")
                collected_data["borme"] = None

            try:
                from app.services.scrapers.google_news import fetch_google_news
                collected_data["google_news"] = await fetch_google_news(
                    company.name, str(analysis.id), db, domain=company_domain
                )
            except Exception as e:
                logger.warning(f"Google News failed: {e}")
                collected_data["google_news"] = None

            try:
                from app.services.scrapers.wikipedia import fetch_wikipedia
                collected_data["wikipedia"] = await fetch_wikipedia(
                    company.name, str(analysis.id), db
                )
            except Exception as e:
                logger.warning(f"Wikipedia failed: {e}")
                collected_data["wikipedia"] = None

            try:
                from app.services.scrapers.app_stores import fetch_app_stores
                collected_data["app_stores"] = await fetch_app_stores(
                    company.name, str(analysis.id), db, domain=company_domain
                )
            except Exception as e:
                logger.warning(f"App Stores failed: {e}")
                collected_data["app_stores"] = None

            try:
                from app.services.scrapers.github import fetch_github
                collected_data["github"] = await fetch_github(
                    company.name, str(analysis.id), db, domain=company_domain
                )
            except Exception as e:
                logger.warning(f"GitHub failed: {e}")
                collected_data["github"] = None

            try:
                from app.services.scrapers.similarweb import fetch_similarweb
                collected_data["similarweb"] = await fetch_similarweb(
                    company.website_url, str(analysis.id), db
                )
            except Exception as e:
                logger.warning(f"SimilarWeb failed: {e}")
                collected_data["similarweb"] = None

            try:
                from app.services.scrapers.glassdoor import fetch_glassdoor
                collected_data["glassdoor"] = await fetch_glassdoor(
                    company.name, str(analysis.id), db
                )
            except Exception as e:
                logger.warning(f"Glassdoor failed: {e}")
                collected_data["glassdoor"] = None

            # ── STEP 3: Normalize ──────────────────────────────────────────
            await _update_step(analysis, "normalizing_data", db)
            from app.services.normalizer import normalize_collected_data
            normalized = normalize_collected_data(
                collected_data,
                company_name=company.name or "",
                company_domain=company_domain,
            )

            # ── STEPS 4-8: LLM modules ─────────────────────────────────────
            await _update_step(analysis, "llm_classifier", db)
            from app.services.llm.classifier import run_classifier
            classification = await run_classifier(
                company.name, company.website_url, normalized,
                str(analysis.id), db, language=language,
            )

            # Build initial deterministic analysis context (no corporate structure yet)
            from app.services.llm.calibration import (
                build_analysis_context,
                apply_risk_filter,
                apply_executive_summary_risk_filter,
                validate_outputs as calibration_validate,
            )
            analysis_context = build_analysis_context(classification, normalized, language=language)

            await _update_step(analysis, "llm_business_model", db)
            from app.services.llm.business_model import run_business_model
            biz_model = await run_business_model(
                classification, normalized, str(analysis.id), db, language=language,
            )

            await _update_step(analysis, "llm_traction", db)
            from app.services.llm.traction import run_traction
            traction = await run_traction(
                classification, normalized, str(analysis.id), db, language=language,
            )

            await _update_step(analysis, "llm_risks", db)
            from app.services.llm.risks import run_risks
            risks = await run_risks(
                classification, biz_model, traction, normalized,
                str(analysis.id), db, language=language,
            )
            # Deterministic risk filter — enforces public/private calibration rules
            risks = apply_risk_filter(risks, analysis_context)

            await _update_step(analysis, "llm_management", db)
            from app.services.llm.management import run_management
            management = await run_management(
                classification, normalized, str(analysis.id), db, language=language,
            )

            # 2A: Source-level management override for established company with no executives.
            # Fixes contamination at source so conclusion, validator, and executive_summary
            # all receive the correct extraction-limitation framing — not downstream rewrites.
            # Skipped under DISABLE_CALIBRATION=1 (mode B experiment).
            if (
                not _calibration_disabled()
                and analysis_context.get("is_established_company")
                and not (management or {}).get("executives")
            ):
                management = dict(management)
                if (language or "es").lower().startswith("es"):
                    management["leadership_analysis"] = (
                        "El pipeline público de extracción no ha recuperado perfiles ejecutivos "
                        "en esta ejecución. Para una empresa consolidada como esta, debe "
                        "interpretarse como una limitación de extracción de datos de management, "
                        "no como evidencia de debilidad o inestabilidad del equipo directivo. "
                        "La calidad y permanencia del liderazgo se verificarán durante el due diligence."
                    )
                else:
                    management["leadership_analysis"] = (
                        "No executive profiles were extracted by the current public-source pipeline. "
                        "For an established company, this should be treated as a management-data "
                        "extraction limitation, not evidence of leadership weakness or instability. "
                        "Leadership quality and retention require direct due diligence."
                    )
                if "team_stability" in management:
                    management["team_stability"] = "unknown"
                if "confidence" in management:
                    management["confidence"] = "low"
                logger.info(
                    "Orchestrator 2A: management leadership_analysis overridden — "
                    "established company, no executives extracted. analysis_id=%s",
                    str(analysis.id),
                )

            await _update_step(analysis, "llm_competitive_position", db)
            from app.services.llm.competitive_position import run_competitive_position
            comp_position = await run_competitive_position(
                classification, biz_model, normalized, str(analysis.id), db, language=language,
            )

            await _update_step(analysis, "llm_operational_signals", db)
            from app.services.llm.operational_signals import run_operational_signals
            operational = await run_operational_signals(
                classification, normalized, str(analysis.id), db, language=language,
            )

            await _update_step(analysis, "llm_corporate_structure", db)
            from app.services.llm.corporate_structure import run_corporate_structure
            corp_structure = await run_corporate_structure(
                classification, normalized, str(analysis.id), db, language=language,
            )

            # Rebuild context now that corporate structure is known
            # (entity_detection_status may update if a non-acquirable structure was confirmed)
            analysis_context = build_analysis_context(classification, normalized, corp_structure, language=language)

            # 2B: Source-level corporate structure override for entity_mapping_required.
            # Removes "cannot verify legal existence" / "non-acquirable" framing before it
            # propagates to conclusion and executive_summary as apparent factual input.
            # Skipped under DISABLE_CALIBRATION=1 (mode B experiment).
            if (
                not _calibration_disabled()
                and analysis_context.get("entity_detection_status") == "entity_mapping_required"
            ):
                _cs_acq = dict((corp_structure or {}).get("acquirability_assessment") or {})
                _cs_notes = (_cs_acq.get("acquirability_notes") or "").lower()
                _cs_forbidden = (
                    "cannot verify legal existence",
                    "legal existence cannot",
                    "entity cannot be verified",
                    "entity could not be verified",
                    "non-acquirable",
                    "not acquirable",
                    "critical structural issue",
                    "acquisition cannot proceed",
                    "acquisition is blocked",
                )
                _cs_needs_fix = (
                    any(p in _cs_notes for p in _cs_forbidden)
                    or _cs_acq.get("group_level_acquirable") is False
                )
                if _cs_needs_fix:
                    if (language or "es").lower().startswith("es"):
                        _cs_acq["acquirability_notes"] = (
                            "El pipeline público no ha conseguido mapear la entidad legal exacta. "
                            "Esto constituye un requisito de mapeo para el due diligence, no una "
                            "evidencia de que el negocio no sea adquirible o no exista legalmente."
                        )
                    else:
                        _cs_acq["acquirability_notes"] = (
                            "The public-source pipeline did not map the precise legal entity. "
                            "This is an entity-mapping requirement for due diligence, not evidence "
                            "that the business is non-acquirable or legally non-existent."
                        )
                    _cs_acq["group_level_acquirable"] = None  # unknown, not confirmed blocked
                    corp_structure = dict(corp_structure)
                    corp_structure["acquirability_assessment"] = _cs_acq
                    logger.info(
                        "Orchestrator 2B: acquirability_assessment overridden — "
                        "entity_mapping_required, forbidden language or false non-acquirable "
                        "removed. analysis_id=%s", str(analysis.id),
                    )

            await _update_step(analysis, "llm_conclusion", db)
            from app.services.llm.conclusion import run_conclusion
            conclusion = await run_conclusion(
                classification, biz_model, traction, risks,
                str(analysis.id), db, language=language,
                normalized=normalized,
                management=management,
                corporate_structure=corp_structure,
            )

            # Apply scoring guardrails — enforce DATA ABSENCE ≠ BUSINESS WEAKNESS
            # across all conclusion narrative fields before the validator and exec summary.
            from app.services.llm.scoring_guardrails import apply_scoring_guardrails
            conclusion = apply_scoring_guardrails(
                conclusion, management, corp_structure, analysis_context,
            )

            # ── STEP: OpenAI second-pass validation + correction ───────────
            # Runs after all Gemini modules complete.
            # Returns a corrected version of the full analysis.
            # Degrades gracefully if OPENAI_API_KEY is not configured.
            await _update_step(analysis, "validating_analysis", db)
            from app.services.llm.analysis_validator import validate_analysis
            corrected = await validate_analysis(
                classification=classification,
                business_model=biz_model,
                traction=traction,
                risks=risks,
                management=management,
                competitive_position=comp_position,
                operational_signals=operational,
                corporate_structure=corp_structure,
                conclusion=conclusion,
                normalized=normalized,
                company_name=company.name or "",
                company_domain=company_domain,
                language=language,
                analysis_id=str(analysis.id),
                db=db,
            )

            # Pop degraded marker before extracting sections — do not leak into report.
            # Added by analysis_validator.py when OpenAI call fails entirely.
            _val_degraded = corrected.pop("_validation_degraded", False)
            if _val_degraded:
                logger.warning(
                    "Orchestrator: OpenAI validation DEGRADED — original Gemini analysis "
                    "used without second-pass correction. analysis_id=%s",
                    str(analysis.id),
                )

            # Extract corrected module outputs (validator preserves protected fields)
            c_classification = corrected.get("classification", classification)
            c_biz_model = corrected.get("business_model", biz_model)
            c_traction = corrected.get("traction", traction)
            c_risks = corrected.get("risks", risks)
            c_management = corrected.get("management", management)

            # Post-validation executive injection: deterministic safety net placed
            # AFTER the validator so it cannot be overwritten by LLM correction.
            # Uses the same three-path Wikipedia extraction as management.py.
            # Only fires when both the Gemini module AND the OpenAI validator
            # returned empty executives.
            if not _calibration_disabled() and not (c_management or {}).get("executives"):
                _wiki_data = normalized.get("wikipedia_summary") or {}
                _wiki_kp = _wiki_data.get("key_people") or ""
                _wiki_sm = _wiki_data.get("summary") or ""
                if _wiki_kp or _wiki_sm:
                    from app.services.llm.management import (
                        _parse_key_people_lines,
                        _executives_from_wiki_infobox,
                        _founders_from_prose,
                    )
                    _post_execs = (
                        _parse_key_people_lines(_wiki_kp)
                        or _executives_from_wiki_infobox(_wiki_sm)
                        or _founders_from_prose(_wiki_sm)
                    )
                    if _post_execs:
                        c_management = dict(c_management or {})
                        c_management["executives"] = _post_execs
                        logger.info(
                            "Orchestrator post-validation: injected %d executive(s) "
                            "from Wikipedia — key_people=%r. analysis_id=%s",
                            len(_post_execs), bool(_wiki_kp), str(analysis.id),
                        )
            c_comp_position = corrected.get("competitive_position", comp_position)
            c_operational = corrected.get("operational_signals", operational)
            c_corp_structure = corrected.get("corporate_structure", corp_structure)
            c_conclusion = corrected.get("conclusion", conclusion)
            c_references = corrected.get("references", normalized.get("references", {}))

            # Re-apply risk filter to validator-corrected risks
            # (validator may reintroduce data-gap risks the first filter removed)
            c_risks = apply_risk_filter(c_risks, analysis_context)

            # Re-apply scoring guardrails to validator-corrected conclusion
            # (validator may reintroduce score-attribution or attractiveness-link language)
            c_conclusion = apply_scoring_guardrails(
                c_conclusion, c_management, c_corp_structure, analysis_context,
            )

            # ── Executive summary (investor-grade first page) ──────────────
            await _update_step(analysis, "llm_executive_summary", db)
            from app.services.llm.executive_summary import run_executive_summary
            exec_summary = await run_executive_summary(
                classification=c_classification,
                business_model=c_biz_model,
                traction=c_traction,
                risks=c_risks,
                management=c_management,
                competitive_position=c_comp_position,
                conclusion=c_conclusion,
                analysis_id=str(analysis.id),
                db=db,
                language=language,
                analysis_context=analysis_context,
            )

            # Apply executive summary key_risk filter and validate final outputs
            exec_summary = apply_executive_summary_risk_filter(
                exec_summary, analysis_context, c_risks,
            )
            calibration_validate(analysis_context, c_risks, exec_summary, str(analysis.id))

            # ── Build and persist report ───────────────────────────────────
            await _update_step(analysis, "building_report", db)

            report = Report(
                analysis_id=analysis.id,
                factual_profile=c_classification.get("factual_profile", {}),
                business_model=c_biz_model,
                traction_signals=c_traction,
                risks=c_risks.get("risks", []),
                references=c_references,
                conclusion=c_conclusion,
                management=c_management,
                competitive_position=c_comp_position,
                operational_signals=c_operational,
                corporate_structure=c_corp_structure,
                executive_summary=exec_summary,
                priority_rating=PriorityRating(
                    c_conclusion.get("priority_rating", "insufficient_data")
                ),
            )
            db.add(report)

            analysis.status = AnalysisStatus.COMPLETED
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(f"Analysis {analysis_id} completed successfully")

        except Exception as e:
            from app.services.llm.gemini_client import GeminiQuotaError, GeminiTimeoutError

            if isinstance(e, GeminiQuotaError):
                logger.warning(
                    f"Pipeline halted — Gemini quota exhausted for {analysis_id}: {e}"
                )
                clean_message = (
                    "Gemini API quota exhausted (rate limit 429). "
                    "Wait a few minutes and retry the analysis."
                )
            elif isinstance(e, GeminiTimeoutError):
                logger.warning(
                    f"Pipeline halted — Gemini timeout at step "
                    f"'{analysis.pipeline_step}' for {analysis_id}: {e}"
                )
                clean_message = str(e)
            else:
                logger.error(f"Pipeline failed for {analysis_id}: {e}", exc_info=True)
                # Guard against exceptions whose str() is empty (e.g. bare asyncio.TimeoutError)
                clean_message = str(e) or f"{type(e).__name__} (no message)"

            async with AsyncSessionLocal() as error_db:
                analysis = await error_db.get(Analysis, analysis_id)
                if analysis:
                    analysis.status = AnalysisStatus.FAILED
                    analysis.error_message = clean_message
                    await error_db.commit()
