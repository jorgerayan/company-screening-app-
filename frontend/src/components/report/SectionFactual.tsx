// Renders the factual_profile block from the classifier module.

interface CorporateData {
  legal_name?: string | null;
  company_number?: string | null;
  jurisdiction?: string | null;
  company_type?: string | null;
  status?: string | null;
  incorporation_date?: string | null;
  registered_address?: string | null;
}

interface FactualProfile {
  name?: string;
  website?: string;
  activity?: string;
  sector?: string;
  business_type?: string;
  b2b_or_b2c?: string;
  geography?: string[];
  detected_markets?: string[];
  corporate_data?: CorporateData;
  public_signals?: string[];
  data_source_notes?: string;
}

interface Props {
  data: Record<string, unknown>;
}

const CORPORATE_LABELS: Record<string, string> = {
  legal_name: "Razón social",
  company_number: "Nº de registro",
  jurisdiction: "Jurisdicción",
  company_type: "Forma jurídica",
  status: "Estado",
  incorporation_date: "Fecha de constitución",
  registered_address: "Domicilio registral",
};

export function SectionFactual({ data }: Props) {
  const profile = data as FactualProfile;

  const hasContent =
    profile.activity ||
    profile.corporate_data ||
    profile.public_signals?.length ||
    profile.detected_markets?.length;

  if (!hasContent) return null;

  const corp = profile.corporate_data;
  const corpEntries = corp
    ? (Object.entries(corp) as [string, string | null | undefined][]).filter(
        ([k, v]) => k !== "opencorporates_url" && v != null && v !== ""
      )
    : [];

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Perfil factual
        </h2>
        <div className="flex items-center gap-2">
          {profile.business_type && (
            <span className="text-xs font-medium bg-gray-900 text-white px-2.5 py-0.5 rounded-full">
              {profile.business_type}
            </span>
          )}
          {profile.b2b_or_b2c && (
            <span className="text-xs font-medium bg-gray-100 text-gray-600 px-2.5 py-0.5 rounded-full">
              {profile.b2b_or_b2c}
            </span>
          )}
        </div>
      </div>

      <div className="px-7 py-6 space-y-6">
        {/* Activity */}
        {profile.activity && (
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Actividad
            </h3>
            <p className="text-sm text-gray-700 leading-relaxed">{profile.activity}</p>
          </div>
        )}

        {/* Geography */}
        {profile.geography && profile.geography.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Geografía
            </h3>
            <p className="text-sm text-gray-700">
              {profile.geography.join(" · ")}
            </p>
          </div>
        )}

        {/* Corporate registry data */}
        {corpEntries.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Datos registrales
            </h3>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3 bg-gray-50 rounded-lg p-4">
              {corpEntries.map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs text-gray-400 mb-0.5">
                    {CORPORATE_LABELS[key] ?? key.replace(/_/g, " ")}
                  </dt>
                  <dd className="text-sm text-gray-800 font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {/* Detected markets */}
        {profile.detected_markets && profile.detected_markets.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Segmentos detectados
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {profile.detected_markets.map((m, i) => (
                <span
                  key={i}
                  className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full"
                >
                  {m}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Public signals */}
        {profile.public_signals && profile.public_signals.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Señales públicas observadas
            </h3>
            <ol className="space-y-2">
              {profile.public_signals.map((signal, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-gray-700">
                  <span className="shrink-0 text-xs text-gray-400 font-medium mt-0.5 w-4">
                    {i + 1}.
                  </span>
                  {signal}
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Data source notes */}
        {profile.data_source_notes && (
          <p className="text-xs text-gray-400 border-t border-gray-100 pt-4 italic">
            {profile.data_source_notes}
          </p>
        )}
      </div>
    </section>
  );
}
