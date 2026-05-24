"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import { getReport } from "@/lib/api";
import { AnalysisProgress } from "@/components/progress/AnalysisProgress";
import { ReportShell } from "@/components/report/ReportShell";
import type { ReportResponse } from "@/types/report";

export default function ReportPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const { data: statusData, error: statusError } = useAnalysisStatus(analysisId);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    if (statusData?.status === "completed" && !report) {
      getReport(analysisId)
        .then(setReport)
        .catch((e) => setReportError(e.message));
    }
  }, [statusData?.status, analysisId, report]);

  if (statusError || reportError) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-red-600 text-sm">{statusError ?? reportError}</p>
      </div>
    );
  }

  if (!statusData || (statusData.status !== "completed" && !report)) {
    return (
      <AnalysisProgress
        step={statusData?.pipeline_step ?? null}
        status={statusData?.status ?? "pending"}
        companyName={statusData?.company_name ?? ""}
      />
    );
  }

  if (report) {
    return <ReportShell report={report} />;
  }

  return null;
}
