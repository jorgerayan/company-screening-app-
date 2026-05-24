// Renders the conclusion and scoring block from the conclusion LLM module.

type PriorityRating = "high" | "interesting_with_doubts" | "low" | "insufficient_data";
type ConfidenceLevel = "high" | "medium" | "low";

interface DimensionScore {
  score?: number;
  rationale?: string;
}

interface DimensionScores {
  business_model?: DimensionScore;
  traction_and_growth?: DimensionScore;
  risk_profile?: DimensionScore;
  management_and_team?: DimensionScore;
  competitive_position?: DimensionScore;
  acquirability?: DimensionScore;
}

interface ConclusionData {
  overall_score?: number;
  overall_label?: string;
  score_rationale?: string;
  dimension_scores?: DimensionScores;
  priority_rating: PriorityRating;
  summary: string;
  investment_thesis?: string;
  key_strengths?: string[];
  key_concerns?: string[];
  key_questions?: string[];
  next_steps?: string[];
  confidence: ConfidenceLevel;
  data_limitations?: string | null;
}

interface Props {
  conclusion: ConclusionData;
}

// Score → visual config
function getScoreConfig(score: number): { barColor: string; labelStyle: string; label: string } {
  if (score === 0) return { barColor: "bg-gray-200", labelStyle: "text-gray-400", label: "Información insuficiente" };
  if (score >= 9.0) return { barColor: "bg-gray-900", labelStyle: "text-gray-900", label: "Oportunidad excepcional" };
  if (score >= 7.5) return { barColor: "bg-gray-800", labelStyle: "text-gray-900", label: "Alta prioridad" };
  if (score >= 6.0) return { barColor: "bg-gray-600", labelStyle: "text-gray-700", label: "Interesante con potencial" };
  if (score >= 4.5) return { barColor: "bg-yellow-400", labelStyle: "text-yellow-800", label: "Interesante con dudas" };
  if (score >= 3.0) return { barColor: "bg-orange-400", labelStyle: "text-orange-800", label: "Baja prioridad" };
  return { barColor: "bg-red-400", labelStyle: "text-red-700", label: "No recomendado" };
}

const DIMENSION_LABELS: Record<string, string> = {
  business_model: "Modelo de negocio",
  traction_and_growth: "Tracción y crecimiento",
  risk_profile: "Perfil de riesgo",
  management_and_team: "Equipo directivo",
  competitive_position: "Posición competitiva",
  acquirability: "Adquiribilidad",
};

const CONFIDENCE_LABELS: Record<ConfidenceLevel, string> = {
  high: "Alta",
  medium: "Media",
  low: "Baja",
};

function ScoreBar({ score }: { score: number }) {
  const config = getScoreConfig(score);
  const pct = score === 0 ? 0 : Math.min(100, (score / 10) * 100);
  return (
    <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
      <div
        className={`h-1.5 rounded-full transition-all ${config.barColor}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function SectionConclusion({ conclusion }: Props) {
  const score = conclusion.overall_score ?? 0;
  const scoreConfig = getScoreConfig(score);
  const label = conclusion.overall_label ?? scoreConfig.label;
  const dims = conclusion.dimension_scores ?? {};
  const hasDims = Object.keys(dims).length > 0;

  const PRIORITY_BORDER: Record<PriorityRating, string> = {
    high: "border-l-4 border-gray-800",
    interesting_with_doubts: "border-l-4 border-yellow-400",
    low: "border-l-4 border-orange-400",
    insufficient_data: "border-l-4 border-gray-300",
  };
  const thesisBorder = PRIORITY_BORDER[conclusion.priority_rating] ?? PRIORITY_BORDER.insufficient_data;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Conclusión y calificación
        </h2>
        <span className="text-xs text-gray-400 font-medium">{label}</span>
      </div>

      <div className="px-7 py-6 space-y-6">

        {/* ── Score hero ── */}
        <div className="flex items-end gap-5">
          {/* Big number */}
          <div className="shrink-0">
            <div className={`text-5xl font-bold tabular-nums leading-none ${scoreConfig.labelStyle}`}>
              {score === 0 ? "—" : score.toFixed(1)}
            </div>
            <div className="text-xs text-gray-400 mt-1">sobre 10</div>
          </div>

          {/* Bar + label + rationale */}
          <div className="flex-1 min-w-0 pb-1">
            <div className="flex items-center justify-between mb-2">
              <span className={`text-sm font-semibold ${scoreConfig.labelStyle}`}>{label}</span>
            </div>
            <ScoreBar score={score} />
            {conclusion.score_rationale && (
              <p className="text-xs text-gray-500 leading-relaxed mt-2.5">
                {conclusion.score_rationale}
              </p>
            )}
          </div>
        </div>

        {/* ── Dimension scores ── */}
        {hasDims && (
          <div className="border-t border-gray-100 pt-5">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
              Desglose por dimensión
            </p>
            <div className="space-y-4">
              {(["business_model", "traction_and_growth", "risk_profile", "management_and_team", "competitive_position", "acquirability"] as const).map((key) => {
                const dim = dims[key];
                if (!dim) return null;
                const dimScore = dim.score ?? 0;
                const dimConfig = getScoreConfig(dimScore);
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-gray-600">
                        {DIMENSION_LABELS[key] ?? key}
                      </span>
                      <span className={`text-sm font-bold tabular-nums ${dimConfig.labelStyle}`}>
                        {dimScore === 0 ? "—" : dimScore.toFixed(1)}
                      </span>
                    </div>
                    <ScoreBar score={dimScore} />
                    {dim.rationale && (
                      <p className="text-xs text-gray-400 mt-1.5 leading-relaxed">
                        {dim.rationale}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Executive summary ── */}
        {conclusion.summary && (
          <div className="border-t border-gray-100 pt-5">
            <p className="text-sm text-gray-700 leading-relaxed">{conclusion.summary}</p>
          </div>
        )}

        {/* ── Investment thesis ── */}
        {conclusion.investment_thesis && (
          <div className={`pl-4 ${thesisBorder}`}>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Tesis de inversión
            </p>
            <p className="text-sm text-gray-700 leading-relaxed">{conclusion.investment_thesis}</p>
          </div>
        )}

        {/* ── Strengths + Concerns ── */}
        {((conclusion.key_strengths?.length ?? 0) > 0 ||
          (conclusion.key_concerns?.length ?? 0) > 0) && (
          <div className="border-t border-gray-100 pt-5 grid grid-cols-1 sm:grid-cols-2 gap-5">
            {conclusion.key_strengths && conclusion.key_strengths.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                  Puntos fuertes
                </p>
                <ul className="space-y-2.5">
                  {conclusion.key_strengths.map((s, i) => (
                    <li key={i} className="text-sm text-gray-700 leading-relaxed pl-3 border-l-2 border-gray-200">
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {conclusion.key_concerns && conclusion.key_concerns.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                  Puntos de atención
                </p>
                <ul className="space-y-2.5">
                  {conclusion.key_concerns.map((c, i) => (
                    <li key={i} className="text-sm text-gray-700 leading-relaxed pl-3 border-l-2 border-gray-200">
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* ── Key questions ── */}
        {conclusion.key_questions && conclusion.key_questions.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Preguntas clave para la siguiente fase
            </p>
            <ul className="space-y-2.5">
              {conclusion.key_questions.map((q, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-gray-700">
                  <span className="shrink-0 text-gray-300 font-bold mt-0.5">→</span>
                  {q}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Next steps ── */}
        {conclusion.next_steps && conclusion.next_steps.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Próximos pasos sugeridos
            </p>
            <ol className="space-y-2">
              {conclusion.next_steps.map((step, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-gray-700">
                  <span className="shrink-0 text-xs font-medium text-gray-400 mt-0.5 w-4">
                    {i + 1}.
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* ── Data limitations ── */}
        {conclusion.data_limitations && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Limitaciones del análisis
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{conclusion.data_limitations}</p>
          </div>
        )}

        {/* ── Confidence footer ── */}
        <div className="pt-4 border-t border-gray-100 flex items-center gap-3">
          <span className="text-xs text-gray-400">Confianza del análisis:</span>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
            {CONFIDENCE_LABELS[conclusion.confidence] ?? conclusion.confidence}
          </span>
          <span className="text-xs text-gray-300 ml-auto hidden sm:block">
            Basado en fuentes públicas. No sustituye due diligence.
          </span>
        </div>
      </div>
    </section>
  );
}
