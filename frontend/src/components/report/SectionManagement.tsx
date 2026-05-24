// Renders the management team section from the management LLM module.

interface Executive {
  name?: string;
  role?: string;
  background?: string;
  source?: string;
  evidence_type?: string;
}

interface ManagementData {
  executives?: Executive[];
  leadership_analysis?: string;
  founder_profile?: string | null;
  team_stability?: "stable" | "uncertain" | "signs_of_instability" | "unknown";
  stability_analysis?: string;
  public_reputation?: string | null;
  recent_changes?: string | null;
  red_flags?: string[];
  confidence?: string;
  data_limitations?: string | null;
}

interface Props {
  data: Record<string, unknown>;
}

const STABILITY_CONFIG: Record<string, { label: string; style: string }> = {
  stable: { label: "Estable", style: "bg-gray-900 text-white" },
  uncertain: { label: "Incierto", style: "bg-yellow-100 text-yellow-800" },
  signs_of_instability: { label: "Señales de inestabilidad", style: "bg-red-100 text-red-700" },
  unknown: { label: "Desconocido", style: "bg-gray-100 text-gray-500" },
};

const SOURCE_LABELS: Record<string, string> = {
  website: "Web oficial",
  wikipedia: "Wikipedia",
  google_news: "Google News",
  gdelt: "GDELT",
};

const EVIDENCE_LABELS: Record<string, string> = {
  verified_fact: "Verificado",
  reasonable_inference: "Inferencia",
  unverifiable: "No verificable",
};

export function SectionManagement({ data }: Props) {
  const mgmt = data as ManagementData;
  const executives = mgmt.executives ?? [];
  const redFlags = mgmt.red_flags ?? [];
  const stability = STABILITY_CONFIG[mgmt.team_stability ?? "unknown"] ?? STABILITY_CONFIG.unknown;

  if (!mgmt.leadership_analysis && executives.length === 0) return null;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Equipo directivo
        </h2>
        <div className="flex items-center gap-2">
          {executives.length > 0 && (
            <span className="text-xs text-gray-400">
              {executives.length} directivo{executives.length !== 1 ? "s" : ""} identificado{executives.length !== 1 ? "s" : ""}
            </span>
          )}
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${stability.style}`}>
            {stability.label}
          </span>
        </div>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Leadership analysis */}
        {mgmt.leadership_analysis && (
          <p className="text-sm text-gray-700 leading-relaxed">{mgmt.leadership_analysis}</p>
        )}

        {/* Executives list */}
        {executives.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
              Directivos identificados
            </h3>
            <div className="space-y-4">
              {executives.map((exec, i) => (
                <div key={i} className="flex gap-4">
                  <div className="shrink-0 mt-0.5">
                    <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-xs font-semibold text-gray-500">
                      {(exec.name ?? "?").charAt(0).toUpperCase()}
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <p className="text-sm font-medium text-gray-900">{exec.name ?? "—"}</p>
                      {exec.role && (
                        <span className="text-xs text-gray-500">{exec.role}</span>
                      )}
                    </div>
                    {exec.background && (
                      <p className="text-sm text-gray-600 leading-relaxed">{exec.background}</p>
                    )}
                    <div className="flex items-center gap-2 mt-1.5">
                      {exec.source && (
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                          {SOURCE_LABELS[exec.source] ?? exec.source}
                        </span>
                      )}
                      {exec.evidence_type && (
                        <span className="text-xs text-gray-400">
                          {EVIDENCE_LABELS[exec.evidence_type] ?? exec.evidence_type}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Founder profile */}
        {mgmt.founder_profile && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Perfil fundador
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{mgmt.founder_profile}</p>
          </div>
        )}

        {/* Stability analysis */}
        {mgmt.stability_analysis && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Estabilidad del equipo directivo
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{mgmt.stability_analysis}</p>
          </div>
        )}

        {/* Recent changes */}
        {mgmt.recent_changes && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Cambios recientes en la dirección
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{mgmt.recent_changes}</p>
          </div>
        )}

        {/* Public reputation */}
        {mgmt.public_reputation && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Reputación pública
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{mgmt.public_reputation}</p>
          </div>
        )}

        {/* Red flags */}
        {redFlags.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Señales de alerta
            </h3>
            <div className="space-y-2">
              {redFlags.map((flag, i) => (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-red-400" />
                  <p className="text-sm text-gray-700 leading-relaxed">{flag}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Data limitations */}
        {mgmt.data_limitations && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Limitaciones de datos
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{mgmt.data_limitations}</p>
          </div>
        )}
      </div>
    </section>
  );
}
