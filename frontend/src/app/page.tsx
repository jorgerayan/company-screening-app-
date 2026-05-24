import Link from "next/link";
import { AnalyzeForm } from "../components/analyze/AnalyzeForm";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-3xl mx-auto px-6 py-24">
        <div className="mb-12 text-center">
          <h1 className="text-4xl font-semibold text-gray-900 tracking-tight">
            Preanálisis empresarial
          </h1>
          <p className="mt-4 text-lg text-gray-500 max-w-xl mx-auto">
            Introduce una empresa y su web. Obtendrás un informe estructurado
            de screening basado en datos públicos verificables.
          </p>
          <p className="mt-2 text-sm text-gray-400">
            Este análisis no sustituye una due diligence. Es una primera
            criba basada en información pública.
          </p>
        </div>
        <AnalyzeForm />
      </div>
    </main>
  );
}