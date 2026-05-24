import type { AnalysisStatus } from "@/types/report";

const STEP_LABELS: Record<string, string> = {
  scraping_website: "Extrayendo web oficial…",
  scraping_external_sources: "Consultando fuentes externas…",
  normalizing_data: "Limpiando y estructurando datos…",
  llm_classifier: "Clasificando tipo de negocio…",
  llm_business_model: "Analizando modelo de negocio…",
  llm_traction: "Evaluando señales de tracción…",
  llm_risks: "Detectando riesgos…",
  llm_conclusion: "Generando conclusión…",
  building_report: "Construyendo informe final…",
};

interface Props {
  step: string | null;
  status: AnalysisStatus;
  companyName: string;
}

export function AnalysisProgress({ step, status, companyName }: Props) {
  const label = step ? (STEP_LABELS[step] ?? step) : "Iniciando análisis…";

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-6">
      <div className="max-w-md w-full text-center space-y-6">
        <div className="w-10 h-10 border-4 border-gray-900 border-t-transparent rounded-full animate-spin mx-auto" />
        {companyName && (
          <p className="text-lg font-medium text-gray-900">{companyName}</p>
        )}
        <p className="text-sm text-gray-500">{label}</p>
        {status === "failed" && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
            El análisis ha fallado. Por favor, inténtalo de nuevo.
          </p>
        )}
      </div>
    </div>
  );
}