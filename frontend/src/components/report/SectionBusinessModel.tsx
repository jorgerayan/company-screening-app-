// Renders the business_model block from the business_model LLM module.

interface BusinessModel {
  model_type?: string;
  description?: string;
  what_they_sell?: string;
  who_they_sell_to?: string;
  monetization?: string;
  monetization_detail?: string;
  recurrence?: string;
  recurrence_analysis?: string;
  scalability?: string;
  scalability_analysis?: string;
  operational_dependency?: string;
  differentiation?: string;
  barriers_to_entry?: string | null;
  competitive_landscape?: string;
  pricing_signals?: string | null;
  confidence?: string;
  evidence_type?: string;
  notes?: string | null;
}

interface Props {
  data: Record<string, unknown>;
}

const LEVEL_LABELS: Record<string, { label: string; style: string }> = {
  high: { label: "Alta", style: "bg-gray-900 text-white" },
  medium: { label: "Media", style: "bg-gray-200 text-gray-700" },
  low: { label: "Baja", style: "bg-gray-100 text-gray-500" },
  unknown: { label: "Sin datos", style: "bg-gray-100 text-gray-400" },
};

function LevelBadge({ value }: { value?: string }) {
  const cfg = LEVEL_LABELS[value ?? "unknown"] ?? LEVEL_LABELS.unknown;
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg.style}`}>
      {cfg.label}
    </span>
  );
}

export function SectionBusinessModel({ data }: Props) {
  const bm = data as BusinessModel;

  if (!bm.description && !bm.model_type) return null;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Modelo de negocio
        </h2>
        {bm.model_type && (
          <span className="text-xs font-medium bg-gray-900 text-white px-2.5 py-0.5 rounded-full">
            {bm.model_type}
          </span>
        )}
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Description */}
        {bm.description && (
          <p className="text-sm text-gray-700 leading-relaxed">{bm.description}</p>
        )}

        {/* What/Who grid */}
        {(bm.what_they_sell || bm.who_they_sell_to) && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            {bm.what_they_sell && (
              <div>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Qué venden
                </h3>
                <p className="text-sm text-gray-700 leading-relaxed">{bm.what_they_sell}</p>
              </div>
            )}
            {bm.who_they_sell_to && (
              <div>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  A quién venden
                </h3>
                <p className="text-sm text-gray-700 leading-relaxed">{bm.who_they_sell_to}</p>
              </div>
            )}
          </div>
        )}

        {/* Monetization */}
        {bm.monetization_detail && (
          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center gap-3 mb-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                Monetización
              </h3>
              {bm.monetization && (
                <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                  {bm.monetization}
                </span>
              )}
            </div>
            <p className="text-sm text-gray-700 leading-relaxed">{bm.monetization_detail}</p>
            {bm.pricing_signals && (
              <div className="mt-3 bg-gray-50 rounded-lg px-4 py-3">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  Señales de precio:{" "}
                </span>
                <span className="text-xs text-gray-600">{bm.pricing_signals}</span>
              </div>
            )}
          </div>
        )}

        {/* Recurrence */}
        {bm.recurrence_analysis && (
          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center gap-3 mb-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                Recurrencia de ingresos
              </h3>
              <LevelBadge value={bm.recurrence} />
            </div>
            <p className="text-sm text-gray-700 leading-relaxed">{bm.recurrence_analysis}</p>
          </div>
        )}

        {/* Scalability */}
        {bm.scalability_analysis && (
          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center gap-3 mb-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                Escalabilidad
              </h3>
              <LevelBadge value={bm.scalability} />
            </div>
            <p className="text-sm text-gray-700 leading-relaxed">{bm.scalability_analysis}</p>
          </div>
        )}

        {/* Differentiation + Barriers grid */}
        {(bm.differentiation || bm.barriers_to_entry) && (
          <div className="border-t border-gray-100 pt-5 grid grid-cols-1 sm:grid-cols-2 gap-5">
            {bm.differentiation && (
              <div>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Diferenciación
                </h3>
                <p className="text-sm text-gray-700 leading-relaxed">{bm.differentiation}</p>
              </div>
            )}
            {bm.barriers_to_entry && (
              <div>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Barreras de entrada
                </h3>
                <p className="text-sm text-gray-700 leading-relaxed">{bm.barriers_to_entry}</p>
              </div>
            )}
          </div>
        )}

        {/* Competitive landscape */}
        {bm.competitive_landscape && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Entorno competitivo
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{bm.competitive_landscape}</p>
          </div>
        )}

        {/* Operational dependency */}
        {bm.operational_dependency && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Dependencia operacional
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{bm.operational_dependency}</p>
          </div>
        )}

        {/* Notes */}
        {bm.notes && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Nota analítica
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{bm.notes}</p>
          </div>
        )}
      </div>
    </section>
  );
}
