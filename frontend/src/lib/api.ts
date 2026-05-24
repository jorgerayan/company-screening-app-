const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function createAnalysis(payload: {
  company_name: string;
  website_url: string;
  country?: string;
  sector_hint?: string;
  language?: string;
}): Promise<{ analysis_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/v1/analyses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to create analysis");
  }
  return res.json();
}

export async function getAnalysisStatus(analysisId: string) {
  const res = await fetch(`${API_BASE}/api/v1/analyses/${analysisId}`);
  if (!res.ok) throw new Error("Failed to fetch analysis status");
  return res.json();
}

export async function getReport(analysisId: string) {
  const res = await fetch(
    `${API_BASE}/api/v1/analyses/${analysisId}/report`
  );
  if (!res.ok) throw new Error("Failed to fetch report");
  return res.json();
}