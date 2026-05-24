"use client";

import { useState, useEffect } from "react";
import type { ReportResponse, RiskItem } from "@/types/report";
import { SectionFactual } from "./SectionFactual";
import { SectionBusinessModel } from "./SectionBusinessModel";
import { SectionTraction } from "./SectionTraction";
import { SectionRisks } from "./SectionRisks";
import { SectionReferences } from "./SectionReferences";
import { SectionConclusion } from "./SectionConclusion";
import { SectionManagement } from "./SectionManagement";
import { SectionCompetitivePosition } from "./SectionCompetitivePosition";
import { SectionOperationalSignals } from "./SectionOperationalSignals";
import { SectionCorporateStructure } from "./SectionCorporateStructure";
import { SectionExecutiveSummary } from "./SectionExecutiveSummary";

function getScoreHeaderConfig(score: number): { color: string; bg: string } {
  if (score === 0) return { color: "text-gray-400", bg: "bg-gray-100" };
  if (score >= 7.5) return { color: "text-gray-900", bg: "bg-gray-100" };
  if (score >= 6.0) return { color: "text-gray-700", bg: "bg-gray-100" };
  if (score >= 4.5) return { color: "text-yellow-800", bg: "bg-yellow-100" };
  return { color: "text-red-700", bg: "bg-red-100" };
}

const NAV_SECTIONS = [
  { id: "executive-summary", label: "Resumen ejecutivo" },
  { id: "factual", label: "Perfil factual" },
  { id: "business-model", label: "Modelo de negocio" },
  { id: "traction", label: "Tracción" },
  { id: "risks", label: "Riesgos" },
  { id: "management", label: "Equipo directivo" },
  { id: "competitive-position", label: "Posicionamiento" },
  { id: "operational-signals", label: "Señales operativas" },
  { id: "corporate-structure", label: "Estructura societaria" },
  { id: "conclusion", label: "Conclusión" },
  { id: "references", label: "Fuentes" },
];

interface Props {
  report: ReportResponse;
}

export function ReportShell({ report }: Props) {
  const [activeSection, setActiveSection] = useState<string>("factual");

  const conclusion = report.conclusion as {
    priority_rating: "high" | "interesting_with_doubts" | "low" | "insufficient_data";
    overall_score?: number;
    overall_label?: string;
    summary: string;
    investment_thesis?: string;
    key_strengths?: string[];
    key_concerns?: string[];
    key_questions?: string[];
    next_steps?: string[];
    confidence: "high" | "medium" | "low";
    data_limitations?: string | null;
  };

  const overallScore = typeof conclusion.overall_score === "number" ? conclusion.overall_score : null;
  const overallLabel = conclusion.overall_label ?? null;
  const scoreHeaderConfig = getScoreHeaderConfig(overallScore ?? 0);

  const riskNarrative = (report.conclusion as Record<string, unknown>)
    ?.risk_narrative as string | undefined;
  const riskSummary = (report.conclusion as Record<string, unknown>)
    ?.risk_summary as string | undefined;

  // Track active section via IntersectionObserver
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id);
          }
        });
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
    );

    NAV_SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sticky header */}
      <div className="sticky top-0 z-20 bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between gap-6">
          <div className="flex items-center gap-4 min-w-0">
            <h1 className="text-sm font-bold text-gray-900 truncate">
              {report.company_name}
            </h1>
            <a
              href={report.website_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gray-400 hover:text-gray-600 transition-colors hidden sm:block truncate max-w-[200px]"
            >
              {report.website_url}
            </a>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {overallScore !== null && (
              <div className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded-full ${scoreHeaderConfig.bg}`}>
                <span className={`text-sm font-bold tabular-nums ${scoreHeaderConfig.color}`}>
                  {overallScore.toFixed(1)}
                </span>
                <span className="text-xs text-gray-400 font-normal">/10</span>
                {overallLabel && (
                  <span className={`text-xs font-semibold ml-1 ${scoreHeaderConfig.color}`}>
                    · {overallLabel}
                  </span>
                )}
              </div>
            )}
            {overallScore === null && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500">
                Sin calificación
              </span>
            )}
            <span className="text-xs text-gray-400 hidden md:block">
              {new Date(report.generated_at).toLocaleDateString("es-ES", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}
            </span>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/analyses/${report.analysis_id}/report/pdf`}
              download
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-900 text-white hover:bg-gray-700 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              PDF
            </a>
          </div>
        </div>
      </div>

      {/* Layout: sidebar + content */}
      <div className="max-w-6xl mx-auto px-6 py-8 flex gap-8">
        {/* Sidebar navigation */}
        <nav className="w-52 shrink-0 hidden lg:block">
          <div className="sticky top-20 space-y-0.5">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 px-3">
              Contenido
            </p>
            {NAV_SECTIONS.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className={`block px-3 py-2 rounded-lg text-sm transition-colors ${
                  activeSection === section.id
                    ? "bg-gray-900 text-white font-medium"
                    : "text-gray-500 hover:text-gray-900 hover:bg-gray-100"
                }`}
              >
                {section.label}
              </a>
            ))}
            <div className="pt-4 mt-2 border-t border-gray-100">
              <p className="text-xs text-gray-400 px-3 leading-relaxed">
                Basado en fuentes públicas. No sustituye due diligence.
              </p>
            </div>
          </div>
        </nav>

        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-5">
          {report.executive_summary && (
            <div id="executive-summary">
              <SectionExecutiveSummary
                data={report.executive_summary as Parameters<typeof SectionExecutiveSummary>[0]["data"]}
                companyName={report.company_name}
              />
            </div>
          )}
          <div id="factual">
            <SectionFactual data={report.factual_profile} />
          </div>
          <div id="business-model">
            <SectionBusinessModel data={report.business_model} />
          </div>
          <div id="traction">
            <SectionTraction data={report.traction_signals} />
          </div>
          <div id="risks">
            <SectionRisks
              risks={report.risks as unknown as RiskItem[]}
              riskNarrative={riskNarrative}
              riskSummary={riskSummary}
            />
          </div>
          {report.management && (
            <div id="management">
              <SectionManagement data={report.management} />
            </div>
          )}
          {report.competitive_position && (
            <div id="competitive-position">
              <SectionCompetitivePosition data={report.competitive_position} />
            </div>
          )}
          {report.operational_signals && (
            <div id="operational-signals">
              <SectionOperationalSignals data={report.operational_signals} />
            </div>
          )}
          {report.corporate_structure && (
            <div id="corporate-structure">
              <SectionCorporateStructure data={report.corporate_structure} />
            </div>
          )}
          <div id="conclusion">
            <SectionConclusion conclusion={conclusion} />
          </div>
          <div id="references">
            <SectionReferences data={report.references} />
          </div>
        </div>
      </div>
    </div>
  );
}
