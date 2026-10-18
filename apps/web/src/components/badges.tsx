"use client";

import type { EvidenceClass, RunStatus } from "@aegis/shared-types";

import { Badge } from "@/components/ui";
import { CASE_STATUS, EVIDENCE_CLASS, OUTCOME_TONE, RESULT_KIND, RUN_STATUS, humanize } from "@/lib/format";

export const EvidenceClassBadge = ({ value }: { value: EvidenceClass }) => {
  const c = EVIDENCE_CLASS[value] ?? { label: humanize(value), tone: "slate", description: "" };
  return (
    <Badge tone={c.tone} title={c.description}>
      {c.label}
    </Badge>
  );
};

export const RunStatusBadge = ({ value }: { value: RunStatus | string }) => {
  const s = RUN_STATUS[value as RunStatus] ?? { label: humanize(value), tone: "slate" };
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  );
};

export const JobStatusBadge = ({ value }: { value: string }) => {
  const tone = { queued: "slate", running: "accent", completed: "ok", completed_with_failures: "warn", failed: "danger", cancelled: "slate" }[value] ?? "slate";
  return (
    <Badge tone={tone} dot>
      {humanize(value)}
    </Badge>
  );
};

export const CaseStatusBadge = ({ value }: { value: string }) => {
  const s = CASE_STATUS[value] ?? { label: humanize(value), tone: "slate" };
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  );
};

export const OutcomeBadge = ({ value, label }: { value: string | null | undefined; label?: string | null }) =>
  value ? <Badge tone={OUTCOME_TONE[value] ?? "slate"}>{label ?? humanize(value)}</Badge> : <span className="text-xs text-muted">No completed analysis</span>;

export const ResultKindBadge = ({ value }: { value: string }) => {
  const k = RESULT_KIND[value] ?? { label: humanize(value), tone: "slate", note: "" };
  return (
    <Badge tone={k.tone} title={k.note}>
      {k.label}
    </Badge>
  );
};

export const PriorityBadge = ({ value }: { value: string }) => (
  <Badge tone={{ low: "slate", normal: "accent", high: "warn", urgent: "danger" }[value] ?? "slate"}>{humanize(value)}</Badge>
);

export const DemoBadge = ({ show }: { show: boolean }) => (show ? <Badge tone="warn">DEMO FIXTURE</Badge> : null);

export const ImplementationBadge = ({ value, available }: { value: string; available?: boolean }) => {
  if (value === "placeholder") return <Badge tone="slate">Integration boundary</Badge>;
  if (available === false) return <Badge tone="slate" dot>Not configured</Badge>;
  if (value === "experimental") return <Badge tone="warn">Experimental</Badge>;
  return (
    <Badge tone="ok" dot>
      Operational
    </Badge>
  );
};
