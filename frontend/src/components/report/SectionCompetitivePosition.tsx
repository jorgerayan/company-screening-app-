// Renders the competitive positioning section from the competitive_position LLM module.

interface Competitor {
  name?: string;
  basis?: string;
  source?: string;
  evidence_type?: string;
}

interface CompetitivePositionData {
  main_competitors?: Competitor[];
  market_position?: "leader" | "challenger" | "niche" | "follower" | "unknown";
  position_analysis?: string;
  real_vs_perceived_advantages?: string;
  competitive_threats?: string[];
  sector_trends?: string;
  differentiation_score?: "high" | "medium" | "low" | "unclear";
  differentiation_basis?: string;
  confidence?: string;
  data_limitations?: string | null;
}

interface Props {
  data: Record<string, unknown>;
}

const MARKET_POSITION_CONFIG: Record<string, { label: string; style: string }> = {
  leader: { label: "Líder de mercado", style: "bg-gray-900 text-white" },
  challenger: { label: "Challenger", style: "bg-gray-700 text-white" },
  niche: { label: "Nicho", style: "bg-gray-200 text-gray-700" },
  follower: { label: "Seguidor", style: "bg-gray-100 text-gray-600" },
  unknown: { label: "Posición desconocida", style: "bg-gray-100 text-gray-500" },
};

const DIFF_SCORE_CONFIG: Record<string, { label: string; style: string }> = {
  high: { label: "Alta diferenciación", style: "bg-gray-900 text-white" },
  medium: { label: "Diferenciación media", style: "bg-gray-200 text-gray-700" },
  low: { label: "Baja diferenciación", style: "bg-yellow-100 text-yellow-800" },
  unclear: { label: "Diferenciación incierta", style: "bg-gray-100 text-gray-500" },
};

const EVIDENCE_LABELS: Record<string, string> = {
  verified_fact: "Verificado",
  reasonable_inference: "Inferencia",
  sector_knowledge: "Conocimiento sectorial",
  unverifiable: "No verificable",
};

export function SectionCompetitivePosition({ data }: Props) {
  const comp = data as CompetitivePositionData;
  const competitors = comp.main_competitors ?? [];
  const threats = comp.competitive_threats ?? [];
  const position = MARKET_POSITION_CONFIG[comp.market_position ?? "unknown"] ?? MARKET_POSITION_CONFIG.unknown;
  const diffScore = DIFF_SCORE_CONFIG[comp.differentiation_score ?? "unclear"] ?? DIFF_SCORE_CONFIG.unclear;

  if (!comp.position_analysis && competitors.length === 0) return null;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Posicionamiento competitivo
        </h2>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${diffScore.style}`}>
            {diffScore.label}
          </span>
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${position.style}`}>
            {position.label}
          </span>
        </div>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Position analysis */}
        {comp.position_analysis && (
          <p className="text-sm text-gray-700 leading-relaxed">{comp.position_analysis}</p>
        )}

        {/* Competitors */}
        {competitors.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
              Competidores identificados
            </h3>
            <div className="space-y-3">
              {competitors.map((c, i) => (
                <div key={i} className="flex gap-3 items-start">
                  <div className="shrink-0 mt-0.5">
                    <span className="text-xs font-medium bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                      {i + 1}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <p className="text-sm font-medium text-gray-900">{c.name ?? "—"}</p>
                      {c.evidence_type && (
                        <span className="text-xs text-gray-400">
                          {EVIDENCE_LABELS[c.evidence_type] ?? c.evidence_type}
                        </span>
                      )}
                    </div>
                    {c.basis && (
                      <p className="text-sm text-gray-600 leading-relaxed">{c.basis}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Real vs perceived advantages */}
        {comp.real_vs_perceived_advantages && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Ventajas reales vs. percibidas
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{comp.real_vs_perceived_advantages}</p>
          </div>
        )}

        {/* Differentiation basis */}
        {comp.differentiation_basis && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Base de diferenciación
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{comp.differentiation_basis}</p>
          </div>
        )}

        {/* Competitive threats */}
        {threats.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Amenazas competitivas
            </h3>
            <div className="space-y-3">
              {threats.map((threat, i) => (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-gray-300" />
                  <p className="text-sm text-gray-700 leading-relaxed">{threat}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Sector trends */}
        {comp.sector_trends && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Tendencias del sector
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{comp.sector_trends}</p>
          </div>
        )}

        {/* Data limitations */}
        {comp.data_limitations && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Limitaciones de datos
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{comp.data_limitations}</p>
          </div>
        )}
      </div>
    </section>
  );
}
