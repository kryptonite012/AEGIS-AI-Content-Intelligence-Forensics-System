"use client";

import type { AuditEvent } from "@aegis/shared-types";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Anchor, BookCheck, Link2, ShieldCheck } from "lucide-react";
import * as React from "react";

import { Badge, Button, Callout, ErrorBlock, Hash, Input, LoadingBlock, PageHeader, Panel, SimpleTable, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, humanize } from "@/lib/format";

const STATUS_TONE: Record<string, string> = {
  implemented_and_tested: "ok",
  partially_implemented: "warn",
  documentation_required: "accent",
  external_assessment_required: "violet",
  not_implemented: "danger",
  not_applicable: "slate",
};

function Compliance() {
  const { data, error, isLoading } = useQuery({ queryKey: ["compliance"], queryFn: () => api<any>("/governance/compliance") });
  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock error={error} />;
  const counts = data.controls.reduce((a: Record<string, number>, c: any) => ((a[c.status] = (a[c.status] ?? 0) + 1), a), {});
  return (
    <div className="space-y-5">
      <Callout tone="warn" title="Not a compliance claim">{data.disclaimer}</Callout>
      <div className="flex flex-wrap gap-2">{Object.entries(counts).map(([k, v]) => <Badge key={k} tone={STATUS_TONE[k]}>{humanize(k)}: {v as number}</Badge>)}</div>
      <SimpleTable
        rows={data.controls.map((c: any) => ({ ...c, id: c.id }))}
        columns={[
          { key: "id", header: "ID", render: (c) => <span className="font-mono text-xs">{c.id}</span> },
          { key: "area", header: "Area", render: (c) => <span className="text-xs text-muted">{c.area}</span> },
          { key: "requirement", header: "Requirement", render: (c) => <span className="text-sm">{c.requirement}</span> },
          { key: "status", header: "Status", render: (c) => <Badge tone={STATUS_TONE[c.status]}>{humanize(c.status)}</Badge> },
          { key: "evidence", header: "Evidence / notes", render: (c) => <span className="text-xs text-muted">{c.evidence}</span> },
        ]}
      />
    </div>
  );
}

export default function AuditPage() {
  const { can } = useAuth();
  const [tab, setTab] = React.useState<"events" | "compliance">(can("audit.read") ? "events" : "compliance");
  const [action, setAction] = React.useState("");
  const events = useQuery({ queryKey: ["audit", action], queryFn: () => api<AuditEvent[]>(`/audit/events?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`), enabled: can("audit.read") });
  const head = useQuery({ queryKey: ["audit-head"], queryFn: () => api<any>("/audit/head"), enabled: can("audit.read") });
  const verify = useMutation({ mutationFn: () => api<any>("/audit/verify", { method: "POST" }) });
  return (
    <>
      <PageHeader eyebrow="Governance" title={<span className="flex items-center gap-3"><BookCheck className="h-6 w-6 text-accent" /> Audit & compliance</span>} description="Append-only audit events, each chained to the previous event's hash. Compliance mapping states honestly what is implemented, partial, or requires external assessment." />
      <Tabs value={tab} onChange={setTab} tabs={[...(can("audit.read") ? [{ id: "events" as const, label: "Audit trail" }] : []), { id: "compliance" as const, label: "Compliance mapping" }]} />
      <div className="mt-6">
        {tab === "events" && (
          <div className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <Panel title="Chain integrity" icon={<Link2 className="h-4 w-4" />} actions={<Button size="sm" onClick={() => verify.mutate()} loading={verify.isPending} icon={<ShieldCheck className="h-3.5 w-3.5" />}>Verify entire chain</Button>}>
                {verify.data ? (
                  <Callout tone={verify.data.valid ? "ok" : "danger"} title={verify.data.valid ? `Chain valid — ${verify.data.checked} events recomputed` : `Chain broken at event #${verify.data.broken_at_seq}: ${verify.data.reason}`}>{verify.data.limitation}</Callout>
                ) : (
                  <p className="text-sm text-muted">Recomputes every event hash from its canonical content and the previous hash.</p>
                )}
              </Panel>
              <Panel title="Anchor the chain head" icon={<Anchor className="h-4 w-4" />}>
                {head.data && (
                  <div className="space-y-2 text-sm">
                    <div>Head event #{head.data.seq} · {fmtDate(head.data.occurred_at)}</div>
                    <Hash value={head.data.event_hash} />
                    <p className="text-xs text-muted">{head.data.purpose} Hash chaining alone cannot stop a privileged administrator from rewriting the entire chain.</p>
                  </div>
                )}
              </Panel>
            </div>
            <Panel title="Events" actions={<Input placeholder="Filter by action prefix (e.g. evidence.)" value={action} onChange={(e) => setAction(e.target.value)} className="h-8 w-72 py-1 text-xs" aria-label="Filter actions" />}>
              {events.error ? <ErrorBlock error={events.error} /> : events.isLoading ? <LoadingBlock /> : (
                <SimpleTable
                  dense
                  rows={events.data ?? []}
                  columns={[
                    { key: "seq", header: "#", render: (e: AuditEvent) => <span className="font-mono text-xs text-muted">{e.seq}</span> },
                    { key: "time", header: "Time", render: (e: AuditEvent) => <span className="whitespace-nowrap text-xs">{fmtDate(e.occurred_at)}</span> },
                    { key: "action", header: "Action", render: (e: AuditEvent) => <span className="font-mono text-xs">{e.action}</span> },
                    { key: "actor", header: "Actor", render: (e: AuditEvent) => <span className="text-xs">{e.actor}</span> },
                    { key: "entity", header: "Entity", render: (e: AuditEvent) => <span className="text-xs text-muted">{e.entity_type} {e.entity_id?.slice(0, 8)}</span> },
                    { key: "details", header: "Details", render: (e: AuditEvent) => <span className="block max-w-[320px] truncate font-mono text-[11px] text-muted" title={JSON.stringify(e.details)}>{e.reason ? `reason: ${e.reason} · ` : ""}{JSON.stringify(e.details)}</span> },
                    { key: "hash", header: "Event hash", render: (e: AuditEvent) => <Hash value={e.event_hash} short /> },
                  ]}
                />
              )}
            </Panel>
          </div>
        )}
        {tab === "compliance" && <Panel title="Compliance mapping"><Compliance /></Panel>}
      </div>
    </>
  );
}
