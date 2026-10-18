"use client";

import type { Report } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";
import { FileDown, FileJson, ScrollText } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge, Button, Callout, ErrorBlock, Hash, LoadingBlock, PageHeader, Panel, SimpleTable } from "@/components/ui";
import { api, download } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export default function ReportsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["reports"], queryFn: () => api<Report[]>("/reports") });
  const [verified, setVerified] = React.useState<Record<string, any>>({});
  return (
    <>
      <PageHeader
        eyebrow="Governance"
        title={<span className="flex items-center gap-3"><ScrollText className="h-6 w-6 text-accent" /> Reports</span>}
        description="Every report links evidence hashes, method versions and configurations, keeps automated findings separate from human conclusions, and can be re-verified at any time."
      />
      <div className="mb-6 grid gap-3 md:grid-cols-3">
        <Callout tone="slate" title="Reproducible">The PDF is rendered deterministically from the canonical JSON payload; verification re-renders it and compares hashes.</Callout>
        <Callout tone="slate" title="Immutable once final">Corrections create a new version and preserve the previous record.</Callout>
        <Callout tone="slate" title="Measured language">Reports use “consistent with”, “inconclusive” and “verification succeeded for the supported record” — never certainty claims.</Callout>
      </div>
      <Panel>
        {error ? <ErrorBlock error={error} /> : isLoading ? <LoadingBlock /> : (
          <SimpleTable
            rows={data ?? []}
            empty={<p className="py-8 text-center text-sm text-muted">No reports have been generated.</p>}
            columns={[
              { key: "case", header: "Case", render: (r: Report) => <Link href={`/cases/${r.investigation_id}`} className="text-accent hover:underline">Open case</Link> },
              { key: "v", header: "Version", render: (r: Report) => <span className="font-mono">v{r.version}</span> },
              { key: "status", header: "Status", render: (r: Report) => <Badge tone={r.status === "final" ? "ok" : r.status === "superseded" ? "slate" : "accent"} dot>{r.status}</Badge> },
              { key: "schema", header: "Schema", render: (r: Report) => <span className="font-mono text-xs text-muted">{r.schema_version}</span> },
              { key: "json", header: "Payload SHA-256", render: (r: Report) => <Hash value={r.json_sha256} short /> },
              { key: "gen", header: "Generated", render: (r: Report) => <span className="text-xs text-muted">{fmtDate(r.generated_at)}</span> },
              { key: "int", header: "Integrity", render: (r: Report) => verified[r.id] ? <Badge tone={verified[r.id].intact ? "ok" : "danger"}>{verified[r.id].intact ? "intact" : "tampered"}</Badge> : <button className="text-xs text-accent hover:underline" onClick={() => api(`/reports/${r.id}/verify`, { method: "POST" }).then((v) => setVerified((s) => ({ ...s, [r.id]: v })))}>Verify</button> },
              { key: "dl", header: "", render: (r: Report) => <div className="flex justify-end gap-1"><Button size="sm" variant="ghost" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => download(`/reports/${r.id}/pdf`, "report.pdf")}>PDF</Button><Button size="sm" variant="ghost" icon={<FileJson className="h-3.5 w-3.5" />} onClick={() => download(`/reports/${r.id}/json`, "report.json")}>JSON</Button></div> },
            ]}
          />
        )}
      </Panel>
    </>
  );
}
