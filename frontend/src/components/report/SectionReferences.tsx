// Renders the references block — sources consulted during the analysis.

const SOURCE_TYPE_CONFIG: Record<string, { label: string }> = {
  website: { label: "Web corporativa" },
  opencorporates: { label: "OpenCorporates" },
  gdelt: { label: "GDELT" },
  borme: { label: "BORME" },
  crossref: { label: "CrossRef" },
  google_news: { label: "Google News" },
  wikipedia: { label: "Wikipedia" },
  app_stores: { label: "App Store" },
  github: { label: "GitHub" },
  similarweb: { label: "SimilarWeb" },
  glassdoor: { label: "Glassdoor" },
  other: { label: "Otro" },
};

interface SourceEntry {
  url?: string;
  title?: string;
  source_type?: string;
  accessed_at?: string;
  [key: string]: unknown;
}

interface Props {
  data: Record<string, unknown>;
}

function isSources(value: unknown): value is SourceEntry[] {
  return Array.isArray(value) && value.length > 0;
}

function SourceRow({ source, index }: { source: SourceEntry; index: number }) {
  const typeKey = source.source_type ?? "other";
  const config = SOURCE_TYPE_CONFIG[typeKey] ?? SOURCE_TYPE_CONFIG.other;

  return (
    <li className="flex items-start gap-3 py-3 border-b border-gray-50 last:border-0">
      <span className="shrink-0 text-xs text-gray-300 font-medium mt-0.5 w-5 text-right">
        {index + 1}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {source.title && (
              <p className="text-sm text-gray-800 truncate">{source.title}</p>
            )}
            {source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-gray-400 hover:text-gray-600 hover:underline truncate block mt-0.5"
              >
                {source.url}
              </a>
            )}
          </div>
          <span className="shrink-0 text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
            {config.label}
          </span>
        </div>
      </div>
    </li>
  );
}

export function SectionReferences({ data }: Props) {
  const sources = isSources(data.sources)
    ? (data.sources as SourceEntry[])
    : isSources(data.references)
    ? (data.references as SourceEntry[])
    : null;

  if (!sources || sources.length === 0) return null;

  return (
    <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Fuentes consultadas
        </h2>
        <span className="text-xs text-gray-400">
          {sources.length} fuente{sources.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="px-7 py-2">
        <ol className="divide-y divide-gray-50">
          {sources.map((source, i) => (
            <SourceRow key={i} source={source} index={i} />
          ))}
        </ol>
      </div>
    </section>
  );
}
