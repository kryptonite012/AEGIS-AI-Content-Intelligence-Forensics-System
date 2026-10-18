"use client";

import type { InvestigationSummary, Page } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { FolderKanban, Lock, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { CaseStatusBadge, DemoBadge, PriorityBadge } from "@/components/badges";
import { DataTable } from "@/components/data-table";
import { Button, EmptyState, ErrorBlock, Input, LoadingBlock, PageHeader, Panel, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CASE_STATUS, fmtDate, fmtRelative } from "@/lib/format";

export default function CaseFilesPage() {
  const router = useRouter();
  const { can } = useAuth();
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [priority, setPriority] = React.useState("");
  const [mine, setMine] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [sorting, setSorting] = React.useState<SortingState>([{ id: "updated_at", desc: true }]);
  const sort = sorting[0];
  const params = new URLSearchParams({ page: String(page), page_size: "20", sort: sort?.id ?? "updated_at", order: sort?.desc ? "desc" : "asc" });
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (priority) params.set("priority", priority);
  if (mine) params.set("assigned_to_me", "true");
  const { data, error, isLoading } = useQuery({
    queryKey: ["cases", params.toString()],
    queryFn: () => api<Page<InvestigationSummary>>(`/investigations?${params}`),
    placeholderData: (prev) => prev,
  });
  const columns = React.useMemo<ColumnDef<InvestigationSummary>[]>(
    () => [
      { id: "case_reference", header: "Reference", enableSorting: false, cell: ({ row }) => <span className="font-mono text-xs text-accent">{row.original.case_reference}</span> },
      {
        id: "title",
        header: "Title",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            {row.original.access_classification === "restricted" && <Lock className="h-3.5 w-3.5 text-warn" aria-label="Restricted" />}
            <span className="font-medium">{row.original.title}</span>
            <DemoBadge show={row.original.is_demo_fixture} />
          </div>
        ),
      },
      { id: "media", header: "Media", enableSorting: false, cell: ({ row }) => <span className="text-xs capitalize text-muted">{row.original.media_category}</span> },
      { id: "priority", header: "Priority", cell: ({ row }) => <PriorityBadge value={row.original.priority} /> },
      { id: "status", header: "Status", enableSorting: false, cell: ({ row }) => <CaseStatusBadge value={row.original.status} /> },
      { id: "reviewer", header: "Reviewer", enableSorting: false, cell: ({ row }) => <span className="text-xs text-muted">{row.original.assigned_reviewer?.display_name ?? "Unassigned"}</span> },
      { id: "created_at", header: "Opened", cell: ({ row }) => <span className="text-xs text-muted">{fmtDate(row.original.created_at, false)}</span> },
      { id: "updated_at", header: "Updated", cell: ({ row }) => <span className="text-xs text-muted">{fmtRelative(row.original.updated_at)}</span> },
    ],
    [],
  );
  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="Case files"
        description="Investigations visible to you under your organisation and access classification."
        actions={can("case.create") && <Link href="/investigations/new"><Button variant="primary" icon={<Plus className="h-4 w-4" />}>New investigation</Button></Link>}
      />
      <Panel>
        <div className="mb-4 grid gap-3 md:grid-cols-[1fr_200px_160px_auto]">
          <Input placeholder="Filter by title or reference…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="Filter cases" />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status filter">
            <option value="">All statuses</option>
            {Object.entries(CASE_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <Select value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1); }} aria-label="Priority filter">
            <option value="">All priorities</option>
            {["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setPage(1); }} className="accent-[rgb(59,130,246)]" /> Assigned to me
          </label>
        </div>
        {error ? <ErrorBlock error={error} /> : isLoading || !data ? <LoadingBlock /> : (
          <DataTable
            data={data.items}
            columns={columns}
            sorting={sorting}
            onSortingChange={(s) => { setSorting(s); setPage(1); }}
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            onPageChange={setPage}
            onRowClick={(r) => router.push(`/cases/${r.id}`)}
            empty={<EmptyState title="No investigations match" icon={<FolderKanban className="h-5 w-5" />}>Adjust the filters or open a new investigation.</EmptyState>}
          />
        )}
      </Panel>
    </>
  );
}
