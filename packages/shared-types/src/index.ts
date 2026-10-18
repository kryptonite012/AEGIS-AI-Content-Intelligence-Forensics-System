// API contract types shared by AEGIS clients. Mirrors apps/api response schemas (aegis API v1).

export type UUID = string;

export type EvidenceClass =
  | "statistical_inference"
  | "verified_watermark"
  | "cryptographic_provenance"
  | "media_forensic_observation"
  | "declared_metadata"
  | "process_evidence"
  | "human_assessment";

export type RunStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "insufficient_input"
  | "unsupported_input"
  | "failed"
  | "blocked_by_policy"
  | "cancelled";

export type JobStatus = "queued" | "running" | "completed" | "completed_with_failures" | "failed" | "cancelled";

export type CaseStatus =
  | "draft"
  | "evidence_acquired"
  | "analysis_queued"
  | "analysis_complete"
  | "human_review"
  | "inconclusive"
  | "report_finalized"
  | "archived";

export interface UserRef {
  id: UUID;
  display_name: string;
  email: string;
}

export interface Me {
  id: UUID;
  email: string;
  display_name: string;
  is_system_admin: boolean;
  mfa_enabled: boolean;
  is_demo_account: boolean;
  organization: { id: UUID; name: string; slug: string; allow_external_processing: boolean };
  role: string;
  role_name: string;
  permissions: string[];
  memberships: { organization_id: UUID; organization_name: string; role: string; role_name: string }[];
  environment: { mode: "demo" | "research" | "connected-production"; environment: string; task_mode: string; external_processing_enabled: boolean };
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface InvestigationSummary {
  id: UUID;
  case_reference: string;
  title: string;
  media_category: string;
  priority: "low" | "normal" | "high" | "urgent";
  status: CaseStatus;
  access_classification: string;
  is_demo_fixture: boolean;
  assigned_reviewer: UserRef | null;
  created_at: string;
  updated_at: string;
}

export interface Investigation extends InvestigationSummary {
  purpose: string;
  description: string;
  legal_basis: string | null;
  retention_class: string;
  legal_hold: boolean;
  allow_external_processing: boolean;
  disposition: string | null;
  pending_questions: string[];
  created_by: UserRef;
  archived_at: string | null;
}

export interface EvidenceVersion {
  id: UUID;
  version_no: number;
  kind: "original" | "normalized_text" | "thumbnail" | "redacted" | "correction";
  parent_version_id: UUID | null;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  original_filename: string | null;
  transformations: string[];
  metadata_status: Record<string, unknown>;
  scan_status: string;
  reason: string | null;
  created_at: string;
  purged_at: string | null;
}

export interface Extraction {
  method: string;
  token_count: number;
  tokenizer: string;
  char_count: number;
  sentence_count: number;
  paragraph_count: number;
  pages: number | null;
  language: { code: string | null; confidence: number | null; scripts: Record<string, number>; candidates?: { code: string; probability: number }[]; note?: string };
  warnings: string[];
  transformations: string[];
  ocr_derived: boolean;
  sufficient_for_detection: boolean;
}

export interface EvidenceItem {
  id: UUID;
  investigation_id: UUID;
  display_name: string;
  role: "primary" | "process_evidence";
  modality: "text" | "document" | "image" | "audio" | "video";
  mime_type: string;
  status: "active" | "integrity_alert" | "purged";
  description: string | null;
  acquired_at: string;
  uploaded_by: UserRef;
  is_demo_fixture: boolean;
  extraction: Extraction | null;
  versions: EvidenceVersion[];
}

export interface EvidenceListItem {
  id: UUID;
  investigation_id: UUID;
  display_name: string;
  modality: EvidenceItem["modality"];
  mime_type: string;
  status: EvidenceItem["status"];
  role: string;
  acquired_at: string;
  sha256: string | null;
  size_bytes: number | null;
  is_demo_fixture: boolean;
  latest_job: { id: UUID; status: JobStatus; profile: string; primary_outcome: string | null; primary_label: string | null; created_at: string } | null;
}

export interface Artifact {
  id: UUID;
  name: string;
  media_type: string;
  sha256: string;
  description: string;
  cannot_establish: string;
}

export interface DetectorRun {
  id: UUID;
  position: number;
  method_id: string;
  method_version: string;
  method_name: string;
  evidence_class: EvidenceClass;
  status: RunStatus;
  input_sha256: string;
  config: Record<string, unknown>;
  threshold: number | null;
  summary: string | null;
  output: Record<string, any>;
  output_schema: string;
  score: number | null;
  score_semantics: string | null;
  calibrated: boolean;
  flagged: boolean | null;
  uncertainty: Record<string, any> | null;
  warnings: string[];
  limitations: string[];
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  artifacts: Artifact[];
}

export interface Fusion {
  policy: string;
  primary_outcome: string;
  primary_label: string;
  categories: string[];
  requires_human_review: boolean;
  agreeing: string[];
  conflicting: string[];
  missing: { method_id: string; reason: string }[];
  failed: { method_id: string; reason: string }[];
  not_interpreted: string[];
  calibration_applies: boolean;
  uncertainty_reasons: string[];
  suggested_next_steps: string[];
  statement: string;
}

export interface AnalysisJob {
  id: UUID;
  investigation_id: UUID;
  evidence_item_id: UUID;
  evidence_version_id: UUID;
  profile_id: string;
  status: JobStatus;
  methods_total: number;
  methods_done: number;
  options: Record<string, unknown>;
  external_processing_permitted: boolean;
  attempts: number;
  cancel_requested: boolean;
  fusion: Fusion | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  runs: DetectorRun[];
}

export interface JobSummary {
  id: UUID;
  evidence_item_id: UUID;
  profile_id: string;
  status: JobStatus;
  methods_total: number;
  methods_done: number;
  created_at: string;
  finished_at: string | null;
}

export interface ProfileMethod {
  id: string;
  name: string;
  evidence_class: EvidenceClass;
  implementation: "operational" | "requires_configuration" | "experimental" | "placeholder";
  available: boolean;
  reason: string;
  modalities: string[];
  external_processing: boolean;
}

export interface AnalysisProfile {
  id: string;
  name: string;
  description: string;
  modalities: string[];
  resources: string;
  limitations: string[];
  methods: ProfileMethod[];
}

export interface Report {
  id: UUID;
  investigation_id: UUID;
  version: number;
  status: "draft" | "final" | "superseded";
  supersedes_id: UUID | null;
  correction_reason: string | null;
  schema_version: string;
  json_sha256: string;
  pdf_sha256: string | null;
  generated_at: string;
  finalized_at: string | null;
}

export interface AuditEvent {
  seq: number;
  id: UUID;
  occurred_at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  investigation_id?: string | null;
  reason: string | null;
  details: Record<string, unknown>;
  correlation_id?: string | null;
  prev_hash?: string;
  event_hash: string;
}

export interface MethodInfo {
  id: string;
  name: string;
  version: string;
  modalities: string[];
  evidence_class: EvidenceClass;
  implementation: ProfileMethod["implementation"];
  description: string;
  output_semantics: string;
  limitations: string[];
  references: string[];
  requires: string[];
  external_processing: boolean;
  available: boolean;
  availability_reason: string;
}

export interface HealthComponent {
  id: string;
  name: string;
  group: string;
  status: "operational" | "unavailable" | "unknown";
  detail: string;
}

export interface RateEstimate {
  value: number | null;
  numerator: number;
  denominator: number;
  interval: { low: number; high: number; method: string; confidence: number } | null;
}

export interface OperatingPoint {
  target_fpr: number;
  threshold: number | null;
  achieved_fpr: number | null;
  tpr: RateEstimate | null;
  negatives: number;
  min_negatives_required: number;
  estimable: boolean;
  note: string;
}

export type ResultKind = "published" | "reproduced" | "locally_measured" | "simulated" | "vendor_reported";

export interface BenchmarkRun {
  id: UUID;
  dataset_id: UUID | null;
  method_id: string;
  method_version: string;
  result_kind: ResultKind;
  status: string;
  seed: number;
  config: Record<string, any>;
  manifest: Record<string, any>;
  metrics: Record<string, any>;
  source_citation: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Dataset {
  id: UUID;
  name: string;
  version: string;
  modality: string;
  provenance: string;
  license: string;
  consent_basis: string;
  documentation: string;
  is_synthetic: boolean;
  sha256: string;
  n_samples: number;
  splits: Record<string, number>;
  fields: string[];
  duplicate_report: Record<string, number>;
  created_at: string;
}

export interface Notification {
  id: UUID;
  kind: string;
  severity: "info" | "warning" | "error" | "critical";
  title: string;
  body: string;
  link: string | null;
  created_at: string;
  read_at: string | null;
}
