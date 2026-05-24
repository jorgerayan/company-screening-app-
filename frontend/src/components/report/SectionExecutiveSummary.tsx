// Executive Summary — first page of the M&A report.
// Sharp, investor-grade layout. Score + what it does + snapshot + risks + verdict.

type PriorityRating = "high" | "interesting_with_doubts" | "low" | "insufficient_data";
type DataConfidence = "high" | "medium" | "low";

interface ExecutiveSummaryData {
  what_it_does: string | null;
  investment_snapshot: string[];
  key_risks: string[];
  final_verdict: string | null;
  final_score: number;
  score_label: string;
  priority_rating: PriorityRating;
  computed_data_confidence: DataConfidence;
}

interface Props {
  data: ExecutiveSummaryData;
  companyName: string;
}

function getScoreStyle(score: number): {
  numColor: string;
  barColor: string;
  badgeBg: string;
  badgeText: string;
} {
  if (score === 0) return { numColor: "text-gray-400", barColor: "bg-gray-200", badgeBg: "bg-gray-100", badgeText: "text-gray-500" };
  if (score >= 7.5) return { numColor: "text-gray-900", barColor: "bg-gray-900", badgeBg: "bg-gray-900", badgeText: "text-white" };
  if (score >= 6.0) return { numColor: "text-gray-800", barColor: "bg-gray-700", badgeBg: "bg-gray-100", badgeText: "text-gray-800" };
  if (score >= 4.5) return { numColor: "text-yellow-800", barColor: "bg-yellow-400", badgeBg: "bg-yellow-100", badgeText: "text-yellow-800" };
  return { numColor: "text-red-700", barColor: "bg-red-400", badgeBg: "bg-red-100", badgeText: "text-red-700" };
}

const CONFIDENCE_CONFIG: Record<DataConfidence, { label: string; dot: string; text: string }> = {
  high:   { label: "Alta",  dot: "bg-gray-800", text: "text-gray-700" },
  medium: { label: "Media", dot: "bg-yellow-400", text: "text-yellow-700" },
  low:    { label: "Baja",  dot: "bg-orange-400", text: "text-orange-700" },
};

export function SectionExecutiveSummary({ data, companyName }: Props) {
  const score = data.final_score ?? 0;
  const style = getScoreStyle(score);
  const pct = score === 0 ? 0 : Math.min(100, (score / 10) * 100);
  const confidence = CONFIDENCE_CONFIG[data.computed_data_confidence] ?? CONFIDENCE_CONFIG.low;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">

      {/* Header */}
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Resumen ejecutivo
        </h2>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-0.5 rounded-full ${confidence.text} bg-gray-50 border border-gray-100`}>
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${confidence.dot}`} />
            Confianza {confidence.label}
          </span>
        </div>
      </div>

      <div className="px-7 py-7 space-y-7">

        {/* ── Score block ── */}
        <div className="flex items-start gap-6">
          {/* Score number */}
          <div className="shrink-0 text-center">
            <div className={`text-6xl font-bold tabular-nums leading-none ${style.numColor}`}>
              {score === 0 ? "—" : score.toFixed(1)}
            </div>
            <div className="text-xs text-gray-400 mt-1 text-center">/ 10</div>
          </div>

          {/* Label + bar */}
          <div className="flex-1 pt-2">
            <div className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold mb-3 ${style.badgeBg} ${style.badgeText}`}>
              {data.score_label || "Sin calificación"}
            </div>
            <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
              <div
                className={`h-2 rounded-full transition-all ${style.barColor}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-xs text-gray-400 mt-2">
              Puntuación de adquiribilidad — basada en fuentes públicas
            </p>
          </div>
        </div>

        {/* ── What it does ── */}
        {data.what_it_does && (
          <div className="border-t border-gray-100 pt-6">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">
              Qué hace
            </p>
            <p className="text-sm text-gray-800 leading-relaxed font-medium">
              {data.what_it_does}
            </p>
          </div>
        )}

        {/* ── Investment snapshot + Key risks — 2 columns ── */}
        {(data.investment_snapshot.length > 0 || data.key_risks.length > 0) && (
          <div className="border-t border-gray-100 pt-6 grid grid-cols-1 md:grid-cols-2 gap-6">

            {/* Snapshot */}
            {data.investment_snapshot.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Snapshot de inversión
                </p>
                <ul className="space-y-2.5">
                  {data.investment_snapshot.map((bullet, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-sm text-gray-700">
                      <span className="shrink-0 mt-1 w-1.5 h-1.5 rounded-full bg-gray-900 inline-block" />
                      {bullet}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Key risks */}
            {data.key_risks.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Riesgos críticos
                </p>
                <ul className="space-y-2.5">
                  {data.key_risks.map((risk, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-sm text-gray-700">
                      <span className="shrink-0 mt-1 w-1.5 h-1.5 rounded-full bg-red-400 inline-block" />
                      {risk}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* ── Final verdict ── */}
        {data.final_verdict && (
          <div className="border-t border-gray-100 pt-6">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Veredicto final
            </p>
            <div className="pl-4 border-l-4 border-gray-900">
              <p className="text-sm text-gray-800 leading-relaxed">
                {data.final_verdict}
              </p>
            </div>
          </div>
        )}

        {/* ── Footer disclaimer ── */}
        <div className="border-t border-gray-100 pt-4 flex items-center justify-between">
          <p className="text-xs text-gray-400">
            {companyName} — Pre-screening M&A
          </p>
          <p className="text-xs text-gray-300">
            Basado en fuentes públicas. No sustituye due diligence.
          </p>
        </div>

      </div>
    </section>
  );
}
