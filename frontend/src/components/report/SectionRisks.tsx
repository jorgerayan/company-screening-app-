// Renders the risks block from the risks LLM module.

import type { RiskItem } from "@/types/report";

interface Props {
  risks: RiskItem[];
  riskNarrative?: string;
  riskSummary?: string;
}

const SEVERITY_CONFIG = {
  high: {
    label: "Alto",
    badgeStyle: "bg-red-100 text-red-700",
    borderStyle: "border-l-4 border-red-400",
  },
  medium: {
    label: "Medio",
    badgeStyle: "bg-yellow-100 text-yellow-700",
    borderStyle: "border-l-4 border-yellow-400",
  },
  low: {
    label: "Bajo",
    badgeStyle: "bg-gray-100 text-gray-500",
    borderStyle: "border-l-4 border-gray-300",
  },
};

export function SectionRisks({ risks, riskNarrative, riskSummary }: Props) {
  if (!risks || risks.length === 0) return null;

  const sorted = [...risks].sort((a, b) => {
    const order = { high: 0, medium: 1, low: 2 };
    return (order[a.severity] ?? 3) - (order[b.severity] ?? 3);
  });

  const highCount = risks.filter((r) => r.severity === "high").length;
  const medCount = risks.filter((r) => r.severity === "medium").length;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Riesgos
        </h2>
        <div className="flex items-center gap-2">
          {highCount > 0 && (
            <span className="text-xs font-semibold bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
              {highCount} alto{highCount !== 1 ? "s" : ""}
            </span>
          )}
          {medCount > 0 && (
            <span className="text-xs font-semibold bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
              {medCount} medio{medCount !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Risk narrative */}
        {riskNarrative && (
          <p className="text-sm text-gray-700 leading-relaxed">{riskNarrative}</p>
        )}
        {!riskNarrative && riskSummary && (
          <p className="text-sm text-gray-700 leading-relaxed">{riskSummary}</p>
        )}

        {/* Risk list */}
        <div className={`space-y-5 ${riskNarrative || riskSummary ? "border-t border-gray-100 pt-5" : ""}`}>
          {sorted.map((risk, i) => {
            const cfg =
              SEVERITY_CONFIG[risk.severity] ?? SEVERITY_CONFIG.low;
            return (
              <div
                key={i}
                className={`pl-4 ${cfg.borderStyle}`}
              >
                <div className="flex items-start gap-3 mb-2">
                  <h3 className="text-sm font-semibold text-gray-900 flex-1">
                    {risk.name}
                  </h3>
                  <span
                    className={`shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full ${cfg.badgeStyle}`}
                  >
                    {cfg.label}
                  </span>
                </div>

                {risk.explanation && (
                  <p className="text-sm text-gray-700 leading-relaxed mb-3">
                    {risk.explanation}
                  </p>
                )}

                {risk.evidence && (
                  <p className="text-xs text-gray-500 mb-3">
                    <span className="font-medium">Evidencia: </span>
                    {risk.evidence}
                  </p>
                )}

                {risk.what_to_validate && (
                  <div className="bg-gray-50 rounded-lg px-4 py-3">
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">
                      Cómo validar
                    </p>
                    <p className="text-sm text-gray-600 leading-relaxed">
                      {risk.what_to_validate}
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
