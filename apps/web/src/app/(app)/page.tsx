"use client";

import type { HealthComponent } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, FileStack, FolderOpen, Gauge, Hourglass, Scale } from "lucide-react";
import Link from "next/link";

import { CaseStatusBadge, DemoBadge, ResultKindBadge } from "@/components/badges";
import { Bars } from "@/components/charts";
import { SystemMap } from "@/components/system-map";
import { Button, Callout, EmptyState, ErrorBlock, LoadingBlock, PageHeader, Panel, SimpleTable, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CASE_STATUS, fmtNum, fmtRelative, humanize } from "@/lib/format";

export default function OverviewPage() {
  const { me, can } = useAuth();
  const { data, error, isLoading } = useQuery({ queryKey: ["overview"], queryFn: () => api<any>("/overview"), refetchInterval: 30_000 });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ components: HealthComponent[]; methods: { available: boolean }[]; jobs: Record<string, number> }>("/health/components"),
    enabled: can("system.health"),
  });
  if (isLoading) return <LoadingBlock label="Loading overview" />;
  if (error) return <ErrorBlock error={error} />;
  const inv = data.investigations;
  const statusData = Object.keys(CASE_STATUS)
    .map((k) => ({ status: CASE_STATUS[k].label, count: inv.by_status[k] ?? 0 }))
    .filter((r) => r.count > 0);
  const outcomeData = Object.entries(data.automated_outcomes as Record<string, number>).map(([k, v]) => ({ outcome: humanize(k), count: v }));
  return (
    <>
      <PageHeader
        eyebrow={`${me?.organization.name} · ${me?.role_name}`}
        title="Overview"
        description="Every figure below is a live count from this organisation's records. Cases marked DEMO FIXTURE are synthetic."
        actions={
          can("case.create") && (
            <Link href="/investigations/new">
              <Button variant="primary">New investigation</Button>
            </Link>
          )
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <Stat label="Investigations" value={inv.total} hint={inv.demo_fixtures ? `${inv.demo_fixtures} demo fixtures` : "no demo fixtures"} icon={<FolderOpen className="h-4 w-4" />} />
        <Stat label="Awaiting review" value={inv.awaiting_review} tone="violet" icon={<Scale className="h-4 w-4" />} hint="in human review" />
        <Stat label="Evidence items" value={data.evidence_items} tone="cyan" icon={<FileStack className="h-4 w-4" />} hint="acquired and hashed" />
        <Stat label="Completed analyses" value={data.jobs.completed} tone="ok" icon={<CheckCircle2 className="h-4 w-4" />} hint={`${data.jobs.by_status.completed_with_failures ?? 0} with method failures`} />
        <Stat label="Inconclusive" value={inv.inconclusive} tone="warn" icon={<Gauge className="h-4 w-4" />} hint="reviewer-recorded" />
        <Stat label="Queue" value={data.jobs.active} tone="accent" icon={<Hourglass className="h-4 w-4" />} hint="queued or running jobs" />
      </div>

      {health.data && (
        <Panel className="mt-6" title="System health" subtitle="Logical processing pipeline — status from live component checks" icon={<Activity className="h-4 w-4" />} actions={<Link href="/health" className="text-xs text-accent hover:underline">Details</Link>}>
          <SystemMap components={health.data.components} methodsAvailable={health.data.methods.filter((m) => m.available).length} methodsTotal={health.data.methods.length} />
        </Panel>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Recent cases" actions={<Link href="/cases" className="text-xs text-accent hover:underline">All case files</Link>}>
          <SimpleTable
            rows={data.recent_cases}
            empty={<EmptyState title="No investigations yet" icon={<FolderOpen className="h-5 w-5" />}>Create an investigation to acquire evidence.</EmptyState>}
            columns={[
              { key: "ref", header: "Reference", render: (r) => <Link href={`/cases/${r.id}`} className="font-mono text-xs text-accent hover:underline">{r.case_reference}</Link> },
              { key: "title", header: "Title", render: (r) => <span className="flex items-center gap-2"><span className="truncate">{r.title}</span><DemoBadge show={r.is_demo_fixture} /></span> },
              { key: "status", header: "Status", render: (r) => <CaseStatusBadge value={r.status} /> },
              { key: "updated", header: "Updated", render: (r) => <span className="text-xs text-muted">{fmtRelative(r.updated_at)}</span> },
            ]}
          />
        </Panel>
        <Panel title="Cases by status">
          {statusData.length ? <Bars data={statusData} x="status" bars={[{ key: "count", name: "cases" }]} horizontal height={Math.max(160, statusData.length * 36)} colorByIndex /> : <p className="text-sm text-muted">No cases.</p>}
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Panel title="Automated outcomes" subtitle="Descriptive categories from the fusion policy — not determinations">
          {outcomeData.length ? <Bars data={outcomeData} x="outcome" bars={[{ key: "count", name: "jobs" }]} horizontal height={Math.max(160, outcomeData.length * 38)} colorByIndex /> : <p className="text-sm text-muted">No completed analyses.</p>}
        </Panel>
        <Panel title="Evaluation performance" subtitle="Latest completed benchmark run">
          {data.latest_benchmark ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <ResultKindBadge value={data.latest_benchmark.result_kind} />
                <span className="font-mono text-xs text-muted">{data.latest_benchmark.method_id}</span>
              </div>
              <div className="text-3xl font-semibold tabular-nums">{fmtNum(data.latest_benchmark.auroc, 3)}</div>
              <div className="text-xs text-muted">AUROC on n = {data.latest_benchmark.n ?? "—"} test samples</div>
              {data.latest_benchmark.result_kind === "simulated" && <Callout tone="warn">Simulated benchmark. Not evidence of real-world performance.</Callout>}
              <Link href={`/benchmarks?run=${data.latest_benchmark.id}`} className="text-xs text-accent hover:underline">Open in Benchmark Laboratory</Link>
            </div>
          ) : (
            <EmptyState title="No benchmark runs" icon={<AlertTriangle className="h-5 w-5" />}>
              False-positive and false-negative trends appear only once validated, labelled evaluation data has been measured.
            </EmptyState>
          )}
        </Panel>
        <Panel title="Recent audit events" actions={can("audit.read") && <Link href="/audit" className="text-xs text-accent hover:underline">Audit trail</Link>}>
          {can("audit.read") ? (
            <ul className="space-y-2.5">
              {data.recent_audit_events.map((e: any) => (
                <li key={e.seq} className="flex items-start gap-3 text-sm">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-ink">{e.action}</div>
                    <div className="truncate text-[11px] text-muted">{e.actor} · {fmtRelative(e.occurred_at)}</div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Audit events are visible to auditors and administrators.</p>
          )}
        </Panel>
      </div>
      {!!Object.keys(data.detector_runs || {}).length && (
        <Panel className="mt-6" title="Detector run outcomes" subtitle="Unavailable and failed runs are counted separately and never as negative detections">
          <Bars data={Object.entries(data.detector_runs).map(([k, v]) => ({ status: humanize(k), runs: v }))} x="status" bars={[{ key: "runs" }]} height={200} colorByIndex />
        </Panel>
      )}
    </>
  );
}
