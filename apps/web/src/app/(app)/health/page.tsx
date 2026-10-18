"use client";

import type { HealthComponent } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";

import { Bars } from "@/components/charts";
import { MethodCapabilities } from "@/components/methods";
import { SystemMap } from "@/components/system-map";
import { Badge, ErrorBlock, LoadingBlock, PageHeader, Panel, SimpleTable } from "@/components/ui";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";

export default function HealthPage() {
  const { data, error, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ mode: string; environment: string; components: HealthComponent[]; methods: any[]; jobs: Record<string, number>; external_processing_enabled: boolean }>("/health/components"),
    refetchInterval: 15_000,
  });
  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock error={error} />;
  const d = data!;
  return (
    <>
      <PageHeader eyebrow="Operations" title={<span className="flex items-center gap-3"><Activity className="h-6 w-6 text-accent" /> System health</span>} description={`Live checks run on request. Last updated ${new Date(dataUpdatedAt).toLocaleTimeString()}. Environment: ${d.environment}, mode: ${d.mode}.`} />
      <Panel title="Processing pipeline"><SystemMap components={d.components} methodsAvailable={d.methods.filter((m) => m.available).length} methodsTotal={d.methods.length} /></Panel>
      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Components">
          <SimpleTable rows={d.components} columns={[
            { key: "name", header: "Component", render: (c: HealthComponent) => <span className="font-medium">{c.name}</span> },
            { key: "group", header: "Group", render: (c: HealthComponent) => <span className="text-xs text-muted">{c.group}</span> },
            { key: "status", header: "Status", render: (c: HealthComponent) => <Badge tone={c.status === "operational" ? "ok" : c.status === "unknown" ? "warn" : "danger"} dot>{c.status === "unknown" ? "not configured" : c.status}</Badge> },
            { key: "detail", header: "Detail", render: (c: HealthComponent) => <span className="text-xs text-muted">{c.detail}</span> },
          ]} />
          <p className="mt-3 text-xs text-muted">External processing (deployment kill switch): {d.external_processing_enabled ? "enabled" : "disabled — no evidence can leave this deployment"}.</p>
        </Panel>
        <Panel title="Jobs by status">
          {Object.keys(d.jobs).length ? <Bars data={Object.entries(d.jobs).map(([k, v]) => ({ status: humanize(k), jobs: v }))} x="status" bars={[{ key: "jobs" }]} horizontal height={220} colorByIndex /> : <p className="text-sm text-muted">No jobs recorded.</p>}
        </Panel>
      </div>
      <div className="mt-6"><MethodCapabilities title="Analysis methods" /></div>
    </>
  );
}
