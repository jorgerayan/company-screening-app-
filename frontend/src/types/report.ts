export type AnalysisStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed";

export type PriorityRating =
  | "high"
  | "interesting_with_doubts"
  | "low"
  | "insufficient_data";

export type ConfidenceLevel = "high" | "medium" | "low";

export type EvidenceType =
  | "verified_fact"
  | "reasonable_inference"
  | "unverifiable";

export interface RiskItem {
  name: string;
  severity: "high" | "medium" | "low";
  evidence: string;
  explanation: string;
  what_to_validate: string;
  evidence_type: EvidenceType;
}

export interface AnalysisStatusResponse {
  analysis_id: string;
  status: AnalysisStatus;
  pipeline_step: string | null;
  company_name: string;
  website_url: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface ReportResponse {
  report_id: string;
  analysis_id: string;
  company_name: string;
  website_url: string;
  factual_profile: Record<string, unknown>;
  business_model: Record<string, unknown>;
  traction_signals: Record<string, unknown>;
  risks: RiskItem[];
  references: Record<string, unknown>;
  conclusion: {
    priority_rating: PriorityRating;
    summary: string;
    key_questions: string[];
    confidence: ConfidenceLevel;
  };
  management: Record<string, unknown> | null;
  competitive_position: Record<string, unknown> | null;
  operational_signals: Record<string, unknown> | null;
  corporate_structure: Record<string, unknown> | null;
  executive_summary: {
    what_it_does: string | null;
    investment_snapshot: string[];
    key_risks: string[];
    final_verdict: string | null;
    final_score: number;
    score_label: string;
    priority_rating: PriorityRating;
    computed_data_confidence: "high" | "medium" | "low";
  } | null;
  priority_rating: PriorityRating;
  generated_at: string;
}