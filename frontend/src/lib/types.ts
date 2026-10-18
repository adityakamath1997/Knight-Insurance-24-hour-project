export type FieldName =
  | "business_name"
  | "requested_effective_date"
  | "garaging_state"
  | "operations_description"
  | "declared_vehicle_count"
  | "operating_radius_miles"
  | "hazardous_materials"
  | "loss_runs_present"
  | "schedule_vehicle_count";

export type FieldState = "KNOWN" | "MISSING" | "CONFLICT" | "INVALID";
export type FieldValue = string | number | boolean | null;
export type RuleStatus = "PASS" | "FLAG" | "UNKNOWN";
export type OverallStatus = "READY_FOR_REVIEW" | "NEEDS_REVIEW";

export interface Evidence {
  source_file: string;
  locator: string;
  excerpt_or_observation: string;
}

export interface Candidate {
  source: string;
  source_file: string;
  raw_value: string | null;
  state: FieldState;
  value: FieldValue;
  evidence: Evidence[];
}

export interface Override {
  value: FieldValue;
  note: string | null;
  created_at: string;
  original_state: FieldState;
  original_value: FieldValue;
}

export interface ReviewedField {
  name: FieldName;
  state: FieldState;
  value: FieldValue;
  candidates: Candidate[];
  inspected_sources: string[];
  attachment_inventory: string[];
  override: Override | null;
}

export interface RuleInput {
  state: FieldState;
  value: FieldValue;
  overridden: boolean;
}

export interface RuleResult {
  id: string;
  name: string;
  status: RuleStatus;
  reason: string;
  inputs: Record<string, RuleInput>;
}

export interface DocumentSummary {
  file_name: string;
  kind: string;
  readable: boolean;
  detected_type: string | null;
}

export interface SourceRunSummary {
  source: "email" | "pdf" | "attachments";
  status: "SUCCEEDED" | "MODEL_FAILED" | "VALIDATION_FAILED" | "SKIPPED";
  attempts: number;
  error: string | null;
}

export interface Message {
  role: "reviewer" | "assistant";
  content: string;
  created_at: string;
}

export interface Narrative {
  status: "SUCCEEDED" | "FAILED" | "NOT_RUN";
  error: string | null;
  summary: string | null;
  draft: { body: string; edited: boolean; stale: boolean };
  messages: Message[];
}

export interface SubmissionDetail {
  id: string;
  created_at: string;
  documents: DocumentSummary[];
  source_runs: SourceRunSummary[];
  fields: Record<FieldName, ReviewedField>;
  rules: RuleResult[];
  overall_status: OverallStatus;
  narrative: Narrative;
}

export type ProgressStage = "prepare" | "extraction" | "rules" | "narrative";
export type ProgressKind =
  | "stage_started"
  | "stage_finished"
  | "agent_message"
  | "tool_call"
  | "tool_result";
export type SourceName = "email" | "pdf" | "attachments";

export interface ProgressEvent {
  kind: ProgressKind;
  stage: ProgressStage;
  source: SourceName | null;
  label: string;
  status: string | null;
  tool: string | null;
  detail: string | null;
  truncated: boolean;
}

export interface SubmissionListItem {
  id: string;
  created_at: string;
  business_name: string | null;
  overall_status: OverallStatus;
  document_count: number;
}

export type SortField = "created_at" | "id" | "status" | "business_name";
export type SortOrder = "asc" | "desc";
