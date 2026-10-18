"use client";

import type { EvidenceListItem } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, Vault } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { DemoBadge, OutcomeBadge } from "@/components/badges";
import { Badge, Callout, ErrorBlock, Hash, Input, LoadingBlock, PageHeader, Panel, Select, SimpleTable, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtBytes, fmtDate, humanize } from "@/lib/format";

export default function EvidenceVaultPage() {
  const [q, setQ] = React.useState("");
  const [modality, setModality] = React.useState("");
  const { data, error, isLoading } = useQuery({
    queryKey: ["evidence", "vault", q, modality],
    queryFn: () => api<EvidenceListItem[]>(`/evidence?limit=500${modality ? `&modality=${modality}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });
  const rows = data ?? [];
  const alerts = rows.filter((r) => r.status === "integrity_alert").length;
  const total = rows.reduce((a, r) => a + (r.size_bytes ?? 0), 0);
  return (
    <>
      <PageHeader
        eyebrow="Chain of custody"
        title={<span className="flex items-center gap-3"><Vault className="h-6 w-6 text-accent" /> Evidence vault</span>}
        description="Originals are content-addressed and write-once. Every operation is recorded in the hash-chained audit trail; integrity verification recomputes stored hashes on demand."
      />
      <div className="mb-6 grid gap-4 md:grid-cols-4">
        <Stat label="Evidence items" value={rows.length} />
        <Stat label="Stored originals" value={fmtBytes(total)} tone="cyan" />
        <Stat label="Integrity alerts" value={alerts} tone={alerts ? "danger" : "ok"} icon={<ShieldAlert className="h-4 w-4" />} />
        <Stat label="Process evidence" value={rows.filter((r) => r.role === "process_evidence").length} tone="violet" />
      </div>
      {alerts > 0 && <div className="mb-6"><Callout tone="danger" title="Integrity alert">At least one stored item no longer matches its acquisition hash. It is blocked from analysis until investigated.</Callout></div>}
      <Panel>
        <div className="mb-4 grid gap-3 md:grid-cols-[1fr_200px]">
          <Input placeholder="Search by name or SHA-256 prefix" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search evidence" />
          <Select value={modality} onChange={(e) => setModality(e.target.value)} aria-label="Modality">
            <option value="">All modalities</option>
            {["text", "document", "image", "audio", "video"].map((m) => <option key={m} value={m}>{m}</option>)}
          </Select>
        </div>
        {error ? <ErrorBlock error={error} /> : isLoading ? <LoadingBlock /> : (
          <SimpleTable
            rows={rows}
            columns={[
              { key: "name", header: "Evidence", render: (r: EvidenceListItem) => <Link href={`/cases/${r.investigation_id}?evidence=${r.id}`} className="flex items-center gap-2 text-accent hover:underline">{r.display_name}<DemoBadge show={r.is_demo_fixture} /></Link> },
              { key: "modality", header: "Type", render: (r: EvidenceListItem) => <span className="text-xs text-muted">{r.modality} · {r.mime_type}</span> },
              { key: "sha", header: "SHA-256 (original)", render: (r: EvidenceListItem) => <Hash value={r.sha256} short /> },
              { key: "size", header: "Size", render: (r: EvidenceListItem) => <span className="text-xs tabular-nums">{fmtBytes(r.size_bytes)}</span> },
              { key: "status", header: "Status", render: (r: EvidenceListItem) => <Badge tone={r.status === "active" ? "ok" : "danger"} dot>{humanize(r.status)}</Badge> },
              { key: "outcome", header: "Latest automated outcome", render: (r: EvidenceListItem) => <OutcomeBadge value={r.latest_job?.primary_outcome} label={r.latest_job?.primary_label} /> },
              { key: "acq", header: "Acquired", render: (r: EvidenceListItem) => <span className="text-xs text-muted">{fmtDate(r.acquired_at)}</span> },
            ]}
          />
        )}
      </Panel>
    </>
  );
}
