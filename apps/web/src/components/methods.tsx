"use client";

import type { MethodInfo } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";

import { EvidenceClassBadge, ImplementationBadge } from "@/components/badges";
import { Badge, Panel, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

export function useMethods() {
  return useQuery({ queryKey: ["detectors"], queryFn: () => api<(MethodInfo & { registry: any })[]>("/detectors") });
}

/** Capability table: every method with its true operational status in this environment. */
export function MethodCapabilities({ modality, title = "Methods for this modality", classes }: { modality?: string; title?: string; classes?: string[] }) {
  const { data } = useMethods();
  if (!data) return <Skeleton className="h-40 w-full" />;
  const rows = data.filter((m) => (!modality || m.modalities.includes(modality)) && (!classes || classes.includes(m.evidence_class)));
  return (
    <Panel title={title} subtitle="Status reflects this deployment. Unconfigured methods return 'unavailable', never a score.">
      <ul className="-my-2 divide-y divide-line/50">
        {rows.map((m) => (
          <li key={m.id} className="flex flex-col gap-2 py-3 md:flex-row md:items-start">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{m.name}</span>
                <span className="font-mono text-[11px] text-muted">{m.id} v{m.version}</span>
                {m.external_processing && <Badge tone="warn">sends evidence externally</Badge>}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted">{m.description}</p>
              <p className="mt-1 text-xs text-ink/70">Output: {m.output_semantics}</p>
              {!m.available && <p className="mt-1 text-xs text-warn/90">{m.availability_reason}</p>}
              {!!m.references?.length && <p className="mt-1 text-[11px] text-muted">Ref: {m.references.join(" · ")}</p>}
            </div>
            <div className="flex shrink-0 gap-1.5">
              <EvidenceClassBadge value={m.evidence_class} />
              <ImplementationBadge value={m.implementation} available={m.available} />
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
