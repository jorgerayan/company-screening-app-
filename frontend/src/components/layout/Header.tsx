import Link from "next/link";

export function Header() {
  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
        <Link
          href="/"
          className="text-sm font-semibold text-gray-900 tracking-tight hover:text-gray-600 transition-colors"
        >
          Screening
        </Link>
        <span className="text-xs text-gray-400">Preanálisis empresarial</span>
      </div>
    </header>
  );
}
