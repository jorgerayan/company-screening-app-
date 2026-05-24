import re
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.database import get_db
from app.models.company import Company
from app.models.analysis import Analysis, AnalysisStatus
from app.models.report import Report
from app.schemas.analysis import (
    AnalysisCreateRequest,
    AnalysisCreateResponse,
    AnalysisStatusResponse,
)
from app.schemas.report import ReportResponse, RiskItem
from app.services.analysis_orchestrator import run_analysis_pipeline

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post("/", response_model=AnalysisCreateResponse, status_code=202)
async def create_analysis(
    payload: AnalysisCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Create or reuse company
    company = Company(
        name=payload.company_name,
        website_url=str(payload.website_url),
        country=payload.country,
        sector_hint=payload.sector_hint,
        language=payload.language or "es",
    )
    db.add(company)
    await db.flush()

    # Create analysis record
    analysis = Analysis(company_id=company.id, status=AnalysisStatus.PENDING)
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    # Launch pipeline in background
    background_tasks.add_task(run_analysis_pipeline, str(analysis.id))

    return AnalysisCreateResponse(
        analysis_id=analysis.id,
        status=AnalysisStatus.PENDING,
        message="Analysis queued. Poll /analyses/{id} for status.",
    )


@router.get("/{analysis_id}", response_model=AnalysisStatusResponse)
async def get_analysis_status(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    company = await db.get(Company, analysis.company_id)

    return AnalysisStatusResponse(
        analysis_id=analysis.id,
        status=analysis.status,
        pipeline_step=analysis.pipeline_step,
        company_name=company.name,
        website_url=company.website_url,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        error_message=analysis.error_message,
    )


@router.get("/{analysis_id}/report", response_model=ReportResponse)
async def get_analysis_report(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if analysis.status != AnalysisStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis not completed. Current status: {analysis.status}",
        )

    report_result = await db.execute(
        select(Report).where(Report.analysis_id == analysis_id)
    )
    report = report_result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    company = await db.get(Company, analysis.company_id)

    return ReportResponse(
        report_id=report.id,
        analysis_id=analysis_id,
        company_name=company.name,
        website_url=company.website_url,
        factual_profile=report.factual_profile,
        business_model=report.business_model,
        traction_signals=report.traction_signals,
        risks=[RiskItem(**r) for r in report.risks],
        references=report.references,
        conclusion=report.conclusion,
        management=report.management,
        competitive_position=report.competitive_position,
        operational_signals=report.operational_signals,
        corporate_structure=report.corporate_structure,
        executive_summary=report.executive_summary,
        priority_rating=report.priority_rating,
        generated_at=report.generated_at,
    )


@router.get("/{analysis_id}/report/pdf")
async def download_report_pdf(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the completed analysis report as a downloadable PDF.
    Only available when analysis status is COMPLETED.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if analysis.status != AnalysisStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis not completed. Current status: {analysis.status}",
        )

    report_result = await db.execute(
        select(Report).where(Report.analysis_id == analysis_id)
    )
    report = report_result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    company = await db.get(Company, analysis.company_id)

    logger.info(
        "PDF download requested — analysis_id=%s company=%s",
        analysis_id, company.name,
    )

    # ── DIAGNOSTIC: log exact management.executives from DB before render ────
    _mgmt_raw = report.management or {}
    _execs_in_db = _mgmt_raw.get("executives") or []
    logger.info(
        "PDF render — management.executives from DB: count=%d values=%r — analysis_id=%s",
        len(_execs_in_db),
        [e.get("name") for e in _execs_in_db],
        analysis_id,
    )
    # ─────────────────────────────────────────────────────────────────────────

    from app.services.pdf_generator import generate_report_pdf

    try:
        pdf_bytes = await generate_report_pdf(
            company_name=company.name,
            website_url=company.website_url or "",
            generated_at=report.generated_at,
            factual_profile=report.factual_profile or {},
            business_model=report.business_model or {},
            traction_signals=report.traction_signals or {},
            risks=report.risks or [],
            conclusion=report.conclusion or {},
            references=report.references or {},
            management=report.management,
            competitive_position=report.competitive_position,
            corporate_structure=report.corporate_structure,
            executive_summary=report.executive_summary,
        )
    except Exception as exc:
        logger.exception("PDF generation failed for analysis_id=%s: %s", analysis_id, exc)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc

    logger.info("PDF generated OK — %d bytes — analysis_id=%s", len(pdf_bytes), analysis_id)

    # Safe filename: keep only alphanumeric, hyphens, underscores
    safe_name = re.sub(r"[^\w\-]", "_", company.name or "company")[:40]
    short_id = str(analysis_id)[:8]
    filename = f"analysis-{safe_name}-{short_id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )