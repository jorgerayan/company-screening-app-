"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createAnalysis } from "../../lib/api";

const LANGUAGES = [
  { value: "es", label: "Español" },
  { value: "en", label: "English" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
  { value: "it", label: "Italiano" },
];

export function AnalyzeForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const form = e.currentTarget;
    const data = new FormData(form);

    try {
      const result = await createAnalysis({
        company_name: data.get("company_name") as string,
        website_url: data.get("website_url") as string,
        country: (data.get("country") as string) || undefined,
        sector_hint: (data.get("sector_hint") as string) || undefined,
        language: (data.get("language") as string) || "es",
      });
      router.push(`/report/${result.analysis_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 space-y-5"
    >
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Nombre de la empresa *
        </label>
        <input
          name="company_name"
          type="text"
          required
          placeholder="Ej: Factorial HR"
          className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Web oficial *
        </label>
        <input
          name="website_url"
          type="url"
          required
          placeholder="https://factorialhr.com"
          className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            País (opcional)
          </label>
          <input
            name="country"
            type="text"
            placeholder="ES"
            className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Sector (opcional)
          </label>
          <input
            name="sector_hint"
            type="text"
            placeholder="SaaS, industria, retail…"
            className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Idioma del informe
        </label>
        <select
          name="language"
          defaultValue="es"
          className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900 bg-white"
        >
          {LANGUAGES.map((lang) => (
            <option key={lang.value} value={lang.value}>
              {lang.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!mounted || loading}
        className="w-full bg-gray-900 text-white rounded-lg py-3 text-sm font-medium hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "Lanzando análisis…" : "Analizar empresa"}
      </button>
    </form>
  );
}
