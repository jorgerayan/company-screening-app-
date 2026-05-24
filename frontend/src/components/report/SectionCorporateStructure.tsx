// Renders the corporate structure section from the corporate_structure LLM module.

interface LegalEntity {
  name?: string | null;
  type?: string | null;
  jurisdiction?: string | null;
  incorporation_date?: string | null;
  status?: string | null;
  company_number?: string | null;
  registered_address?: string | null;
}

interface CorporateEvent {
  date?: string | null;
  type?: string;
  description?: string;
  source?: string;
  implication?: string;
}

interface CorporateStructureData {
  legal_entity?: LegalEntity;
  subsidiaries?: string[];
  ownership_signals?: string | null;
  corporate_events?: CorporateEvent[];
  legal_signals?: string[];
  structure_narrative?: string;
  complexity_level?: "simple" | "moderate" | "complex" | "unknown";
  red_flags?: string[];
  confidence?: string;
  data_limitations?: string | null;
}

interface Props {
  data: Record<string, unknown>;
}

const COMPLEXITY_CONFIG: Record<string, { label: string; style: string }> = {
  simple: { label: "Estructura simple", style: "bg-gray-200 text-gray-700" },
  moderate: { label: "Estructura moderada", style: "bg-gray-300 text-gray-700" },
  complex: { label: "Estructura compleja", style: "bg-gray-900 text-white" },
  unknown: { label: "Estructura desconocida", style: "bg-gray-100 text-gray-500" },
};

const EVENT_SOURCE_LABELS: Record<string, string> = {
  borme: "BORME",
  opencorporates: "OpenCorporates",
  google_news: "Google News",
  gdelt: "GDELT",
  website: "Web oficial",
};

export function SectionCorporateStructure({ data }: Props) {
  const corp = data as CorporateStructureData;
  const complexity = COMPLEXITY_CONFIG[corp.complexity_level ?? "unknown"] ?? COMPLEXITY_CONFIG.unknown;
  const entity = corp.legal_entity;
  const events = corp.corporate_events ?? [];
  const subsidiaries = corp.subsidiaries ?? [];
  const legalSignals = corp.legal_signals ?? [];
  const redFlags = corp.red_flags ?? [];

  if (!corp.structure_narrative) return null;

  // Check if entity has any meaningful data
  const hasEntityData = entity && Object.values(entity).some((v) => v != null && v !== "");

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Estructura societaria
        </h2>
        <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${complexity.style}`}>
          {complexity.label}
        </span>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Structure narrative */}
        {corp.structure_narrative && (
          <p className="text-sm text-gray-700 leading-relaxed">{corp.structure_narrative}</p>
        )}

        {/* Legal entity details */}
        {hasEntityData && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Entidad legal
            </h3>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5">
              {entity?.name && (
                <>
                  <dt className="text-xs text-gray-400">Denominación social</dt>
                  <dd className="text-sm text-gray-900">{entity.name}</dd>
                </>
              )}
              {entity?.type && (
                <>
                  <dt className="text-xs text-gray-400">Forma jurídica</dt>
                  <dd className="text-sm text-gray-900">{entity.type}</dd>
                </>
              )}
              {entity?.jurisdiction && (
                <>
                  <dt className="text-xs text-gray-400">Jurisdicción</dt>
                  <dd className="text-sm text-gray-900">{entity.jurisdiction}</dd>
                </>
              )}
              {entity?.incorporation_date && (
                <>
                  <dt className="text-xs text-gray-400">Fecha de constitución</dt>
                  <dd className="text-sm text-gray-900">{entity.incorporation_date}</dd>
                </>
              )}
              {entity?.status && (
                <>
                  <dt className="text-xs text-gray-400">Estado</dt>
                  <dd className="text-sm text-gray-900">{entity.status}</dd>
                </>
              )}
              {entity?.company_number && (
                <>
                  <dt className="text-xs text-gray-400">Número de registro</dt>
                  <dd className="text-sm text-gray-900 font-mono text-xs">{entity.company_number}</dd>
                </>
              )}
              {entity?.registered_address && (
                <>
                  <dt className="text-xs text-gray-400">Domicilio social</dt>
                  <dd className="text-sm text-gray-900">{entity.registered_address}</dd>
                </>
              )}
            </dl>
          </div>
        )}

        {/* Ownership signals */}
        {corp.ownership_signals && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Estructura accionarial
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{corp.ownership_signals}</p>
          </div>
        )}

        {/* Subsidiaries */}
        {subsidiaries.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Filiales y estructura de grupo
            </h3>
            <div className="space-y-2">
              {subsidiaries.map((sub, i) => (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-gray-400" />
                  <p className="text-sm text-gray-700 leading-relaxed">{sub}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Corporate events */}
        {events.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
              Eventos corporativos detectados
            </h3>
            <div className="space-y-4">
              {events.map((event, i) => (
                <div key={i} className="flex gap-4">
                  <div className="shrink-0 text-right w-20">
                    <span className="text-xs text-gray-400">{event.date ?? "—"}</span>
                  </div>
                  <div className="flex-1 min-w-0 border-l border-gray-200 pl-4">
                    <div className="flex items-center gap-2 mb-1">
                      <p className="text-sm font-medium text-gray-900">{event.type ?? "—"}</p>
                      {event.source && (
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                          {EVENT_SOURCE_LABELS[event.source] ?? event.source}
                        </span>
                      )}
                    </div>
                    {event.description && (
                      <p className="text-sm text-gray-600 leading-relaxed mb-1">{event.description}</p>
                    )}
                    {event.implication && (
                      <p className="text-xs text-gray-500 italic">{event.implication}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Legal signals */}
        {legalSignals.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Señales legales y regulatorias
            </h3>
            <div className="space-y-2">
              {legalSignals.map((signal, i) => (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-yellow-400" />
                  <p className="text-sm text-gray-700 leading-relaxed">{signal}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Red flags */}
        {redFlags.length > 0 && (
          <div className="border-t border-gray-100 pt-5">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Señales de alerta estructurales
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
        {corp.data_limitations && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">
              Limitaciones de datos
            </p>
            <p className="text-sm text-yellow-800 leading-relaxed">{corp.data_limitations}</p>
          </div>
        )}
      </div>
    </section>
  );
}
