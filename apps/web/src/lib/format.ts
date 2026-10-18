import type { EvidenceClass, RunStatus } from "@aegis/shared-types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function fmtDate(iso: string | null | undefined, withTime = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

export function fmtRelative(iso: string | null | undefined) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function fmtBytes(n: number | null | undefined) {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${u[i]}`;
}

export function fmtNum(v: number | null | undefined, digits = 3) {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e5)) return v.toExponential(2);
  // Never let rounding make a value look exact (e.g. 0.9999 shown as "1").
  let d = digits;
  while (d < 6 && v !== Math.round(v) && Number(v.toFixed(d)) === Math.round(v)) d++;
  const s = v.toFixed(d);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

/** Percentages that never round to exactly 0% or 100% unless the value is exact. */
export function fmtPctSafe(v: number | null | undefined, digits = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  let d = digits;
  const pctv = v * 100;
  while (d < 4 && pctv !== Math.round(pctv) && [0, 100].includes(Number(pctv.toFixed(d)))) d++;
  return `${pctv.toFixed(d)}%`;
}

export function fmtPct(v: number | null | undefined, digits = 1) {
  return fmtPctSafe(v, digits);
}

export const humanize = (s: string | null | undefined) => (s ? s.replace(/[_.]/g, " ").replace(/\s+/g, " ").trim() : "—");

export const EVIDENCE_CLASS: Record<EvidenceClass, { label: string; tone: string; description: string }> = {
  statistical_inference: {
    label: "Statistical inference",
    tone: "violet",
    description: "Resemblance to known generator behaviour. Never proof of authorship.",
  },
  verified_watermark: {
    label: "Watermark verification",
    tone: "cyan",
    description: "Keyed test for a specific recognised watermark scheme.",
  },
  cryptographic_provenance: {
    label: "Signed provenance",
    tone: "accent",
    description: "Cryptographic validation of a signed record. Claims are not thereby true.",
  },
  media_forensic_observation: {
    label: "Forensic observation",
    tone: "slate",
    description: "Measurements and visualisations for an analyst; not a classifier.",
  },
  declared_metadata: {
    label: "Declared metadata",
    tone: "warn",
    description: "Unsigned, editable claims embedded in the file.",
  },
  process_evidence: { label: "Process evidence", tone: "ok", description: "Drafts, revision history, notes." },
  human_assessment: { label: "Human assessment", tone: "ink", description: "Qualified reviewer conclusion." },
};

export const RUN_STATUS: Record<RunStatus, { label: string; tone: string }> = {
  pending: { label: "Pending", tone: "slate" },
  running: { label: "Running", tone: "accent" },
  completed: { label: "Completed", tone: "ok" },
  unavailable: { label: "Unavailable", tone: "slate" },
  insufficient_input: { label: "Insufficient input", tone: "warn" },
  unsupported_input: { label: "Not applicable", tone: "slate" },
  failed: { label: "Failed", tone: "danger" },
  blocked_by_policy: { label: "Blocked by policy", tone: "warn" },
  cancelled: { label: "Cancelled", tone: "slate" },
};

export const CASE_STATUS: Record<string, { label: string; tone: string; step: number }> = {
  draft: { label: "Draft", tone: "slate", step: 0 },
  evidence_acquired: { label: "Evidence acquired", tone: "accent", step: 1 },
  analysis_queued: { label: "Analysis queued", tone: "cyan", step: 2 },
  analysis_complete: { label: "Analysis complete", tone: "cyan", step: 3 },
  human_review: { label: "Human review", tone: "violet", step: 4 },
  inconclusive: { label: "Inconclusive", tone: "warn", step: 4 },
  report_finalized: { label: "Report finalised", tone: "ok", step: 5 },
  archived: { label: "Archived", tone: "slate", step: 6 },
};

export const OUTCOME_TONE: Record<string, string> = {
  no_reliable_conclusion: "slate",
  inconclusive: "slate",
  some_signals_consistent_with_ai: "violet",
  multiple_compatible_signals_consistent_with_ai: "violet",
  evidence_of_recognized_watermark: "cyan",
  provenance_record_verified: "ok",
  provenance_verification_failed: "danger",
  contradictory_evidence: "warn",
  human_review_required: "accent",
};

export const RESULT_KIND: Record<string, { label: string; tone: string; note: string }> = {
  locally_measured: { label: "Locally measured", tone: "ok", note: "A real method run by AEGIS on registered real data." },
  simulated: { label: "Simulated", tone: "warn", note: "Synthetic data or a synthetic model. Not real-world validation." },
  published: { label: "Published", tone: "accent", note: "Copied from a cited publication; not reproduced here." },
  reproduced: { label: "Reproduced", tone: "cyan", note: "Reproduction of a cited result." },
  vendor_reported: { label: "Vendor-reported", tone: "slate", note: "Provider claim, not independently verified." },
};
