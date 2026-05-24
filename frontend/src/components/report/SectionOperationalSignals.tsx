// Renders the operational signals section from the operational_signals LLM module.

interface HiringSignals {
  detected?: boolean;
  volume?: "high" | "moderate" | "low" | "none" | "unknown";
  role_types?: string | null;
  interpretation?: string;
}

interface EmployerReputation {
  glassdoor_rating?: number | null;
  review_count?: number | null;
  would_recommend_pct?: number | null;
  ceo_approval_pct?: number | null;
  summary?: string;
  red_flags?: string[];
}

interface OperationalSignalsData {
  hiring_signals?: HiringSignals;
  product_launches?: string[];
  geographic_expansion?: string | null;
  employer_reputation?: EmployerReputation;
  tension_signals?: string[];
  operational_narrative?: string;
  overall_health?: "strong" | "stable" | "mixed_signals" | "concerning" | "unknown";
  confidence?: string;
  data_limitations?: string | null;
}

interface Props {
  data: Record<string, unknown>;
}

const HEALTH_CONFIG: Record<string, { label: string; style: string }> = {
  strong: { label: "Salud operativa sólida", style: "bg-gray-900 text-white" },
  stable: { label: "Operaciones estables", style: "bg-gray-200 text-gray-700" },
  mixed_signals: { label: "Señales mixtas", style: "bg-yellow-100 text-yellow-800" },
  concerning: { label: "Señales preocupantes", style: "bg-red-100 text-red-700" },
  unknown: { label: "Estado desconocido", style: "bg-gray-100 text-gray-500" },
};

const HIRING_VOLUME_CONFIG: Record<string, { label: string; style: string }> = {
  high: { label: "Contratación intensa", style: "bg-gray-900 text-white" },
  moderate: { label: "Contratación moderada", style: "bg-gray-200 text-gray-700" },
  low: { label: "Contratación baja", style: "bg-gray-100 text-gray-500" },
  none: { label: "Sin contratación detectada", style: "bg-gray-100 text-gray-400" },
  unknown: { label: "Contratación desconocida", style: "bg-gray-100 text-gray-400" },
};

export function SectionOperationalSignals({ data }: Props) {
  const ops = data as OperationalSignalsData;
  const health = HEALTH_CONFIG[ops.overall_health ?? "unknown"] ?? HEALTH_CONFIG.unknown;
  const hiring = ops.hiring_signals;
  const launches = ops.product_launches ?? [];
  const tensionSignals = ops.tension_signals ?? [];
  const empRep = ops.employer_reputation;
  const empRedFlags = empRep?.red_flags ?? [];

  if (!ops.operational_narrative) return null;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Señales operativas
        </h2>
        <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${health.style}`}>
          {health.label}
        </span>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Operational narrative */}
        {ops.operational_narrative && (
          <p className="text-sm text-gray-700 leading-relaxed">{ops.operational_narrative}</p>
        )}

        {/* Hiring signals */}
        {hiring && (
          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                Señales de contratación
              </h3>
              {hiring.volume && (
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${(HIRING_VOLUME_CONFIG[hiring.volume] ?? HIRING_VOLUME_CONFIG.unknown).style}`}>
                  {(HIRING_VOLUME_CONFIG[hiring.volume] ?? HIRING_VOLUME_CONFIG.unknown).label}
                </span>
              )}
            </div>
            {hiring.role_types && (
              <p className="text-xs text-gray-500 mb-2">Tipos de roles: {hiring.role_types}</p>
            )}
            {hiring.interpretation && (
              <p className="text-sm text-gray-700 leading-relaxed">{hiring.interpretation}</p>
            )}
          </div>
        )}

        {/* Glassdoor / Employer reputation */}
        {empRep && (empRep.glassdoor_rating != null || empRep.summary) && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Reputación como empleador
            </h3>
            {(empRep.glassdoor_rating != null || empRep.review_count != null) && (
              <div className="flex gap-6 mb-3">
                {empRep.glassdoor_rating != null && (
                  <div>
                    <p className="text-xs text-gray-400 mb-0.5">Valoración Glassdoor</p>
                    <p className="text-lg font-semibold text-gray-900">
                      {empRep.glassdoor_rating}
                      <span className="text-xs font-normal text-gray-400"> / 5</span>
                    </p>
                  </div>
                )}
                {empRep.review_count != null && (
                  <div>
                    <p className="text-xs text-gray-400 mb-0.5">Reseñas</p>
                    <p className="text-lg font-semibold text-gray-900">{empRep.review_count.toLocaleString("es-ES")}</p>
                  </div>
                )}
                {empRep.would_recommend_pct != null && (
                  <div>
                    <p className="text-xs text-gray-400 mb-0.5">Lo recomendarían</p>
                    <p className="text-lg font-semibold text-gray-900">{empRep.would_recommend_pct}%</p>
                  </div>
                )}
                {empRep.ceo_approval_pct != null && (
                  <div>
                    <p className="text-xs text-gray-400 mb-0.5">Aprobación CEO</p>
                    <p className="text-lg font-semibold text-gray-900">{empRep.ceo_approval_pct}%</p>
                  </div>
                )}
              </div>
            )}
            {empRep.summary && (
              <p className="text-sm text-gray-700 leading-relaxed">{empRep.summary}</p>
            )}
            {empRedFlags.length > 0 && (
              <div className="mt-3 space-y-1.5">
                {empRedFlags.map((flag, i) => (
                  <div key={i} className="flex gap-2 items-start">
                    <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-red-400" />
                    <p className="text-sm text-gray-600">{flag}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Product launches */}
        {launches.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Lanzamientos de producto / servicio
            </h3>
            <div className="space-y-2">
              {launches.map((launch, i) => (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-gray-400" />
                  <p className="text-sm text-gray-700 leading-relaxed">{launch}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Geographic expansion */}
        {ops.geographic_expansion && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Expansión geográfica
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{ops.geographic_expansion}</p>
          </div>
        )}

        {/* Tension signals */}
        {tensionSignals.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Señales de tensión operativa
            </h3>
            <div className="space-y-2">
              {tensionSignals.map((signal, i) => (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-red-400" />
                  <p className="text-sm text-gray-700 leading-relaxed">{signal}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Data limitations */}
        {ops.data_limitations && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Limitaciones de datos
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{ops.data_limitations}</p>
          </div>
        )}
      </div>
    </section>
  );
}
