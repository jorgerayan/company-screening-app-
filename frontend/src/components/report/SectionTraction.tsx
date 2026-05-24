// Renders the traction_signals block from the traction LLM module.

interface TractionSignal {
  type?: string;
  title?: string;
  evidence?: string;
  interpretation?: string;
  source?: string;
  date?: string | null;
  confidence?: string;
  evidence_type?: string;
}

interface TractionData {
  signals?: TractionSignal[];
  growth_narrative?: string;
  news_summary?: string | null;
  internal_vs_external_consistency?: string;
  data_availability?: string;
  data_gaps?: string;
  overall_confidence?: string;
  notes?: string | null;
}

interface Props {
  data: Record<string, unknown>;
}

const SOURCE_LABELS: Record<string, string> = {
  website: "Web oficial",
  gdelt: "GDELT",
  borme: "BORME",
  opencorporates: "OpenCorporates",
  google_news: "Google News",
  github: "GitHub",
  app_stores: "App Store",
  similarweb: "SimilarWeb",
};

const AVAILABILITY_LABELS: Record<string, { label: string; style: string }> = {
  rich: { label: "Datos ricos", style: "bg-gray-900 text-white" },
  moderate: { label: "Datos moderados", style: "bg-gray-200 text-gray-700" },
  sparse: { label: "Datos escasos", style: "bg-gray-100 text-gray-500" },
};

export function SectionTraction({ data }: Props) {
  const traction = data as TractionData;
  const signals = traction.signals ?? [];

  if (!traction.growth_narrative && signals.length === 0) return null;

  const avail =
    AVAILABILITY_LABELS[traction.data_availability ?? "sparse"] ??
    AVAILABILITY_LABELS.sparse;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Tracción
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">
            {signals.length} señal{signals.length !== 1 ? "es" : ""}
          </span>
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${avail.style}`}>
            {avail.label}
          </span>
        </div>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Growth narrative */}
        {traction.growth_narrative && (
          <p className="text-sm text-gray-700 leading-relaxed">{traction.growth_narrative}</p>
        )}

        {/* Signals list */}
        {signals.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
              Señales identificadas
            </h3>
            <div className="space-y-5">
              {signals.map((signal, i) => (
                <div key={i} className="flex gap-4">
                  <div className="shrink-0 mt-0.5">
                    <span className="text-xs font-medium bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                      {SOURCE_LABELS[signal.source ?? ""] ?? signal.source ?? "—"}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <p className="text-sm font-medium text-gray-900">{signal.title}</p>
                      {signal.date && (
                        <span className="text-xs text-gray-400 shrink-0">{signal.date}</span>
                      )}
                    </div>
                    {signal.evidence && (
                      <p className="text-xs text-gray-500 mb-1.5">{signal.evidence}</p>
                    )}
                    {signal.interpretation && (
                      <p className="text-sm text-gray-700 leading-relaxed">
                        {signal.interpretation}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* News summary */}
        {traction.news_summary && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Cobertura mediática
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{traction.news_summary}</p>
          </div>
        )}

        {/* Internal vs external consistency */}
        {traction.internal_vs_external_consistency && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Consistencia interna vs. externa
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">
              {traction.internal_vs_external_consistency}
            </p>
          </div>
        )}

        {/* Data gaps */}
        {traction.data_gaps && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Limitaciones de datos
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{traction.data_gaps}</p>
          </div>
        )}
      </div>
    </section>
  );
}
