"use client";

import type { EvidenceItem, Investigation, JobSummary, Report } from "@aegis/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  CheckCircle2,
  FileDown,
  FileJson,
  Gavel,
  History,
  Lock,
  MessageSquarePlus,
  RotateCcw,
  Scale,
  Send,
  ShieldCheck,
  Stamp,
  UploadCloud,
  UserCheck,
} from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import * as React from "react";

import { JobView } from "@/components/analysis";
import { CaseStatusBadge, DemoBadge, JobStatusBadge, OutcomeBadge, PriorityBadge } from "@/components/badges";
import { Badge, Button, Callout, Dialog, EmptyState, ErrorBlock, Field, Hash, KV, LoadingBlock, PageHeader, Panel, Select, SimpleTable, Tabs, Textarea } from "@/components/ui";
import { EvidenceCard, RunDialog, UploadDialog } from "@/features/case/evidence";
import { ApiError, api, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CASE_STATUS, cx, fmtDate, fmtRelative, humanize } from "@/lib/format";

type Tab = "overview" | "evidence" | "analysis" | "review" | "reports" | "appeals" | "history";
const FLOW = ["draft", "evidence_acquired", "analysis_queued", "analysis_complete", "human_review", "report_finalized", "archived"];

function Stepper({ status }: { status: string }) {
  const current = CASE_STATUS[status]?.step ?? 0;
  return (
    <ol className="flex flex-wrap items-center gap-y-3">
      {FLOW.map((s, i) => {
        const done = i < current || (status === "archived" && i <= 6);
        const active = (CASE_STATUS[s]?.step ?? i) === current && (s === status || (status === "inconclusive" && s === "human_review"));
        return (
          <li key={s} className="flex items-center">
            <div className={cx("flex items-center gap-2 rounded-full px-3 py-1 text-xs", active ? "bg-accent/15 text-ink ring-1 ring-accent/40" : done ? "text-ok" : "text-muted")}>
              {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className={cx("h-2 w-2 rounded-full", active ? "bg-accent" : "bg-line")} />}
              {active && status === "inconclusive" ? "Inconclusive" : CASE_STATUS[s].label}
            </div>
            {i < FLOW.length - 1 && <div className={cx("mx-1 h-px w-5", done ? "bg-ok/50" : "bg-line")} />}
          </li>
        );
      })}
    </ol>
  );
}

function errMsg(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const { can, me } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = React.useState<Tab>(search.get("evidence") ? "evidence" : "overview");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [runItem, setRunItem] = React.useState<EvidenceItem | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<null | "reopen" | "archive" | "assign" | "hold" | "inconclusive">(null);
  const [reason, setReason] = React.useState("");
  const [actionError, setActionError] = React.useState<string | null>(null);

  const caseQ = useQuery({ queryKey: ["case", id], queryFn: () => api<Investigation>(`/investigations/${id}`) });
  const evidenceQ = useQuery({ queryKey: ["evidence", id], queryFn: () => api<EvidenceItem[]>(`/investigations/${id}/evidence`) });
  const jobsQ = useQuery({ queryKey: ["case", id, "jobs"], queryFn: () => api<JobSummary[]>(`/analysis/investigations/${id}/jobs`), refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 4000 : false) });
  const reviewsQ = useQuery({ queryKey: ["case", id, "reviews"], queryFn: () => api<any[]>(`/investigations/${id}/reviews`) });
  const notesQ = useQuery({ queryKey: ["case", id, "notes"], queryFn: () => api<any[]>(`/investigations/${id}/annotations`) });
  const reportsQ = useQuery({ queryKey: ["case", id, "reports"], queryFn: () => api<Report[]>(`/investigations/${id}/reports`), enabled: can("report.read") });
  const appealsQ = useQuery({ queryKey: ["case", id, "appeals"], queryFn: () => api<any[]>(`/investigations/${id}/appeals`) });
  const historyQ = useQuery({ queryKey: ["case", id, "history"], queryFn: () => api<any[]>(`/investigations/${id}/history`), enabled: tab === "history" });
  const reviewersQ = useQuery({ queryKey: ["case", id, "reviewers"], queryFn: () => api<any[]>(`/investigations/${id}/reviewers`), enabled: dialog === "assign" });

  React.useEffect(() => {
    if (!jobId && jobsQ.data?.length) setJobId(jobsQ.data[0].id);
  }, [jobsQ.data, jobId]);
  React.useEffect(() => {
    const ev = search.get("evidence");
    if (ev && evidenceQ.data) document.getElementById(`evidence-${ev}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [search, evidenceQ.data]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["case", id] });
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      setDialog(null);
      setReason("");
      setActionError(null);
      refresh();
      qc.invalidateQueries({ queryKey: ["evidence", id] });
    },
    onError: (e) => setActionError(errMsg(e)),
  });

  if (caseQ.isLoading) return <LoadingBlock label="Loading case" />;
  if (caseQ.error) return <ErrorBlock error={caseQ.error} />;
  const inv = caseQ.data!;
  const locked = ["report_finalized", "archived"].includes(inv.status);
  const evidence = evidenceQ.data ?? [];
  const jobs = jobsQ.data ?? [];

  const transition = (target: string, why?: string) => act.mutate(() => api(`/investigations/${id}/transition`, { json: { target, reason: why } }));

  return (
    <>
      <PageHeader
        eyebrow={<span className="font-mono">{inv.case_reference}</span>}
        title={
          <span className="flex flex-wrap items-center gap-3">
            {inv.title}
            <DemoBadge show={inv.is_demo_fixture} />
            {inv.access_classification === "restricted" && <Badge tone="warn"><Lock className="h-3 w-3" /> Restricted</Badge>}
            {inv.legal_hold && <Badge tone="danger">Legal hold</Badge>}
          </span>
        }
        description={inv.purpose}
        actions={
          <>
            {can("evidence.upload") && !locked && <Button onClick={() => setUploadOpen(true)} icon={<UploadCloud className="h-4 w-4" />}>Add evidence</Button>}
            {inv.status === "analysis_complete" && can("case.update") && (
              <Button variant="primary" icon={<Send className="h-4 w-4" />} onClick={() => (inv.assigned_reviewer ? transition("human_review") : setDialog("assign"))}>
                Request human review
              </Button>
            )}
            {inv.status === "report_finalized" && can("case.archive") && <Button onClick={() => setDialog("archive")} icon={<Archive className="h-4 w-4" />}>Archive</Button>}
            {["report_finalized", "inconclusive", "archived"].includes(inv.status) && can("case.reopen") && (
              <Button onClick={() => setDialog("reopen")} icon={<RotateCcw className="h-4 w-4" />}>Reopen</Button>
            )}
          </>
        }
      />
      <Panel className="mb-6" bodyClassName="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
        <Stepper status={inv.status} />
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <PriorityBadge value={inv.priority} />
          <span>Reviewer: <span className="text-ink">{inv.assigned_reviewer?.display_name ?? "unassigned"}</span></span>
          {can("case.assign") && !locked && <button className="text-accent hover:underline" onClick={() => setDialog("assign")}>change</button>}
        </div>
      </Panel>
      {actionError && <div className="mb-4"><Callout tone="danger">{actionError}</Callout></div>}

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "evidence", label: "Evidence", count: evidence.length },
          { id: "analysis", label: "Analyses", count: jobs.length },
          { id: "review", label: "Review", count: (reviewsQ.data?.length ?? 0) + (notesQ.data?.length ?? 0) },
          { id: "reports", label: "Reports", count: reportsQ.data?.length },
          { id: "appeals", label: "Appeals", count: appealsQ.data?.length },
          { id: "history", label: "History" },
        ]}
      />
      <div className="mt-6">
        {tab === "overview" && (
          <div className="grid gap-6 xl:grid-cols-3">
            <Panel className="xl:col-span-2" title="Case record">
              <KV
                items={[
                  ["Status", <CaseStatusBadge key="s" value={inv.status} />],
                  ["Media category", humanize(inv.media_category)],
                  ["Created", `${fmtDate(inv.created_at)} by ${inv.created_by.display_name}`],
                  ["Last updated", fmtRelative(inv.updated_at)],
                  ["Legal / organisational basis", inv.legal_basis ?? "Not recorded"],
                  ["Retention class", humanize(inv.retention_class)],
                  ["Access classification", humanize(inv.access_classification)],
                  ["External processing", inv.allow_external_processing ? "Permitted for this case (subject to deployment and organisation settings)" : "Not permitted — local processing only"],
                  ["Final disposition", inv.disposition ? humanize(inv.disposition) : "Not yet recorded"],
                ]}
              />
              {inv.description && <p className="mt-5 whitespace-pre-wrap text-sm leading-relaxed text-ink/85">{inv.description}</p>}
            </Panel>
            <div className="space-y-6">
              <Panel title="Latest automated outcomes">
                {jobs.length ? (
                  <ul className="space-y-3">
                    {jobs.slice(0, 6).map((j) => (
                      <li key={j.id}>
                        <button className="w-full text-left" onClick={() => { setJobId(j.id); setTab("analysis"); }}>
                          <div className="flex items-center justify-between gap-2 text-sm">
                            <span className="truncate">{evidence.find((e) => e.id === j.evidence_item_id)?.display_name ?? "evidence"}</span>
                            <JobStatusBadge value={j.status} />
                          </div>
                          <div className="text-xs text-muted">{humanize(j.profile_id)} · {fmtRelative(j.created_at)}</div>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">No analyses yet.</p>
                )}
              </Panel>
              <Panel title="Safeguards">
                <ul className="space-y-2 text-xs leading-relaxed text-muted">
                  <li className="flex gap-2"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" />Automated outcomes describe evidence. They never constitute a finding of misconduct.</li>
                  <li className="flex gap-2"><Scale className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet" />Decisions affecting a person require independent corroboration and qualified human review.</li>
                  <li className="flex gap-2"><Gavel className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />Affected parties can contest findings through the appeal workflow.</li>
                </ul>
                {can("admin.settings") && (
                  <Button size="sm" variant="ghost" className="mt-4" onClick={() => setDialog("hold")}>{inv.legal_hold ? "Release legal hold" : "Place legal hold"}</Button>
                )}
              </Panel>
            </div>
          </div>
        )}

        {tab === "evidence" && (
          <div className="space-y-4">
            {evidenceQ.isLoading && <LoadingBlock />}
            {!evidence.length && !evidenceQ.isLoading && (
              <EmptyState title="No evidence acquired" icon={<UploadCloud className="h-5 w-5" />} action={can("evidence.upload") && !locked && <Button onClick={() => setUploadOpen(true)}>Add evidence</Button>}>
                Evidence is hashed and stored write-once at acquisition.
              </EmptyState>
            )}
            {evidence.map((e) => <EvidenceCard key={e.id} item={e} caseId={id} locked={locked} onRun={setRunItem} />)}
          </div>
        )}

        {tab === "analysis" && (
          <div className="grid gap-6 xl:grid-cols-[300px_1fr]">
            <Panel title="Analysis jobs" bodyClassName="p-2">
              {!jobs.length && <p className="p-3 text-sm text-muted">No jobs. Run an analysis from the Evidence tab.</p>}
              <ul className="space-y-1">
                {jobs.map((j) => (
                  <li key={j.id}>
                    <button onClick={() => setJobId(j.id)} className={cx("w-full rounded-lg px-3 py-2.5 text-left", jobId === j.id ? "bg-accent/10 ring-1 ring-accent/30" : "hover:bg-raised/60")}>
                      <div className="truncate text-sm">{evidence.find((e) => e.id === j.evidence_item_id)?.display_name}</div>
                      <div className="mt-1 flex items-center gap-2">
                        <JobStatusBadge value={j.status} />
                        <span className="text-[11px] text-muted">{j.methods_done}/{j.methods_total}</span>
                      </div>
                      <div className="mt-1 text-[11px] text-muted">{humanize(j.profile_id)} · {fmtRelative(j.created_at)}</div>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <div>{jobId ? <JobView jobId={jobId} /> : <EmptyState title="Select a job" />}</div>
          </div>
        )}

        {tab === "review" && <ReviewTab inv={inv} reviews={reviewsQ.data ?? []} notes={notesQ.data ?? []} evidence={evidence} meId={me?.id} onChange={refresh} />}

        {tab === "reports" && <ReportsTab inv={inv} reports={reportsQ.data ?? []} onChange={refresh} />}

        {tab === "appeals" && <AppealsTab inv={inv} appeals={appealsQ.data ?? []} onChange={refresh} />}

        {tab === "history" && (
          <Panel title="Case history" subtitle="From the hash-chained audit trail" icon={<History className="h-4 w-4" />}>
            {historyQ.isLoading ? <LoadingBlock /> : (
              <ol className="relative space-y-4 border-l border-line/70 pl-6">
                {historyQ.data?.map((h) => (
                  <li key={h.seq} className="relative">
                    <span className="absolute -left-[29px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" />
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-mono text-xs text-ink">{h.action}</span>
                      <span className="text-xs text-muted">{h.actor} · {fmtDate(h.occurred_at)}</span>
                    </div>
                    {h.reason && <div className="mt-0.5 text-xs text-ink/80">Reason: {h.reason}</div>}
                    {h.details && Object.keys(h.details).length > 0 && <div className="mt-1 truncate font-mono text-[11px] text-muted" title={JSON.stringify(h.details)}>{JSON.stringify(h.details)}</div>}
                    <div className="mt-0.5"><Hash value={h.event_hash} short /></div>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        )}
      </div>

      <UploadDialog caseId={id} open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <RunDialog caseId={id} item={runItem} onClose={() => setRunItem(null)} onQueued={(j) => { setJobId(j); setTab("analysis"); qc.invalidateQueries({ queryKey: ["case", id] }); }} />

      <Dialog open={dialog === "reopen"} onClose={() => setDialog(null)} title="Reopen investigation" footer={<Button variant="primary" disabled={reason.length < 10} loading={act.isPending} onClick={() => transition("human_review", reason)}>Reopen for review</Button>}>
        <Callout tone="warn">Reopening is recorded with your reason. Finalised reports are preserved; changes produce a new report version.</Callout>
        <Field label="Reason" hint="At least 10 characters."><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        {actionError && <Callout tone="danger">{actionError}</Callout>}
      </Dialog>
      <Dialog open={dialog === "archive"} onClose={() => setDialog(null)} title="Archive investigation" footer={<Button variant="primary" loading={act.isPending} onClick={() => transition("archived", reason || undefined)}>Archive</Button>}>
        <Field label="Note (optional)"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Dialog>
      <Dialog open={dialog === "hold"} onClose={() => setDialog(null)} title={inv.legal_hold ? "Release legal hold" : "Place legal hold"} footer={<Button variant="primary" disabled={reason.length < 5} loading={act.isPending} onClick={() => act.mutate(() => api(`/investigations/${id}/legal-hold`, { json: { legal_hold: !inv.legal_hold, reason } }))}>Confirm</Button>}>
        <p className="text-sm text-muted">While on legal hold, deletion requests are blocked.</p>
        <Field label="Reason"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Dialog>
      <Dialog open={dialog === "assign"} onClose={() => setDialog(null)} title="Assign independent reviewer">
        <p className="text-sm text-muted">Reviewers must hold review permission and cannot be the case creator.</p>
        <div className="space-y-2">
          {reviewersQ.data?.map((r) => (
            <button key={r.id} onClick={() => act.mutate(() => api(`/investigations/${id}/assign`, { json: { reviewer_id: r.id } }))} className="flex w-full items-center gap-3 rounded-lg border border-line px-3 py-2.5 text-left text-sm hover:border-accent/50">
              <UserCheck className="h-4 w-4 text-accent" /> {r.display_name} <span className="ml-auto text-xs text-muted">{humanize(r.role)}</span>
            </button>
          ))}
          {reviewersQ.data && !reviewersQ.data.length && <p className="text-sm text-muted">No eligible reviewers in this organisation.</p>}
        </div>
        {actionError && <Callout tone="danger">{actionError}</Callout>}
      </Dialog>
    </>
  );
}

const DECISIONS = [
  "inconclusive",
  "no_reliable_conclusion",
  "some_signals_consistent_with_ai",
  "multiple_compatible_signals_consistent_with_ai",
  "evidence_of_recognized_watermark",
  "provenance_record_verified",
  "provenance_verification_failed",
  "contradictory_evidence",
  "further_analysis_requested",
];

function ReviewTab({ inv, reviews, notes, evidence, meId, onChange }: { inv: Investigation; reviews: any[]; notes: any[]; evidence: EvidenceItem[]; meId?: string; onChange: () => void }) {
  const { can } = useAuth();
  const [decision, setDecision] = React.useState("inconclusive");
  const [rationale, setRationale] = React.useState("");
  const [agrees, setAgrees] = React.useState<"" | "yes" | "no">("");
  const [note, setNote] = React.useState("");
  const [kind, setKind] = React.useState("note");
  const [noteEvidence, setNoteEvidence] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const canDecide = can("review.decide") && inv.status === "human_review" && inv.created_by.id !== meId;
  const submit = async () => {
    setErr(null);
    try {
      await api(`/investigations/${inv.id}/reviews`, { json: { decision, rationale, agrees_with_automated: agrees === "" ? null : agrees === "yes" } });
      setRationale("");
      onChange();
    } catch (e) {
      setErr(errMsg(e));
    }
  };
  const addNote = async () => {
    setErr(null);
    try {
      await api(`/investigations/${inv.id}/annotations`, { json: { body: note, kind, evidence_item_id: noteEvidence || null } });
      setNote("");
      onChange();
    } catch (e) {
      setErr(errMsg(e));
    }
  };
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="Human review decision" subtitle="Recorded separately from automated findings, with a content hash chained into the audit trail" icon={<Scale className="h-4 w-4" />}>
        {canDecide ? (
          <div className="space-y-4">
            <Field label="Assessment">
              <Select value={decision} onChange={(e) => setDecision(e.target.value)}>{DECISIONS.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}</Select>
            </Field>
            <Field label="Agreement with the automated outcome">
              <Select value={agrees} onChange={(e) => setAgrees(e.target.value as any)}>
                <option value="">Not stated</option>
                <option value="yes">Agree</option>
                <option value="no">Disagree (recorded)</option>
              </Select>
            </Field>
            <Field label="Rationale" hint="At least 20 characters. State which evidence supports the assessment and what remains uncertain.">
              <Textarea value={rationale} onChange={(e) => setRationale(e.target.value)} className="min-h-[140px]" />
            </Field>
            <Callout tone="slate">Avoid unsupported statements such as “100% AI-generated” or “definitively human-written”.</Callout>
            <Button variant="primary" disabled={rationale.length < 20} onClick={submit} icon={<Stamp className="h-4 w-4" />}>Record authenticated decision</Button>
          </div>
        ) : (
          <Callout tone="slate">
            {inv.status !== "human_review" ? "Decisions are recorded while the case is in human review." : inv.created_by.id === meId ? "Separation of duties: the case creator cannot record the independent review." : "You do not hold the review permission."}
          </Callout>
        )}
        {err && <div className="mt-3"><Callout tone="danger">{err}</Callout></div>}
        <div className="mt-6 space-y-3">
          {reviews.map((r) => (
            <div key={r.id} className="rounded-lg border border-line/70 bg-bg/40 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <OutcomeBadge value={r.decision} />
                {r.agrees_with_automated === false && <Badge tone="warn">disagrees with automated outcome</Badge>}
                <span className="ml-auto text-xs text-muted">{r.reviewer.display_name} · {fmtDate(r.created_at)}</span>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-ink/90">{r.rationale}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted">
                <span>automated: {humanize(r.automated_outcome)}</span>
                <span>decision hash <Hash value={r.content_sha256} short /></span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Annotations & questions" icon={<MessageSquarePlus className="h-4 w-4" />}>
        {can("review.annotate") && (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Annotation type">
                <option value="note">Note</option>
                <option value="finding">Finding</option>
                <option value="question">Pending question</option>
                <option value="contradiction">Contradictory evidence</option>
              </Select>
              <Select value={noteEvidence} onChange={(e) => setNoteEvidence(e.target.value)} aria-label="Related evidence">
                <option value="">Whole case</option>
                {evidence.map((e) => <option key={e.id} value={e.id}>{e.display_name}</option>)}
              </Select>
            </div>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an annotation…" />
            <Button size="sm" disabled={!note.trim()} onClick={addNote}>Add annotation</Button>
          </div>
        )}
        <ul className="mt-5 space-y-3">
          {notes.map((n) => (
            <li key={n.id} className="rounded-lg border border-line/70 bg-bg/40 p-3">
              <div className="flex items-center gap-2 text-xs">
                <Badge tone={{ finding: "violet", question: "accent", contradiction: "warn" }[n.kind as string] ?? "slate"}>{n.kind}</Badge>
                <span className="text-muted">{n.author.display_name} · {fmtRelative(n.created_at)}</span>
                {n.evidence_item_id && <span className="truncate text-muted">· {evidence.find((e) => e.id === n.evidence_item_id)?.display_name}</span>}
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-sm text-ink/90">{n.body}</p>
            </li>
          ))}
          {!notes.length && <p className="text-sm text-muted">No annotations yet.</p>}
        </ul>
      </Panel>
    </div>
  );
}

function ReportsTab({ inv, reports, onChange }: { inv: Investigation; reports: Report[]; onChange: () => void }) {
  const { can } = useAuth();
  const [err, setErr] = React.useState<string | null>(null);
  const [verify, setVerify] = React.useState<Record<string, any>>({});
  const [correcting, setCorrecting] = React.useState<Report | null>(null);
  const [reason, setReason] = React.useState("");
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr(errMsg(e));
    }
  };
  const locked = ["report_finalized", "archived"].includes(inv.status);
  return (
    <Panel
      title="Forensic reports"
      subtitle="Reproducible PDF and versioned JSON (aegis.report/v1). Finalised reports are immutable; corrections create new versions."
      actions={can("report.generate") && !locked && <Button variant="primary" onClick={() => run(() => api(`/investigations/${inv.id}/reports`, { method: "POST" }))}>Generate draft report</Button>}
    >
      {err && <div className="mb-4"><Callout tone="danger">{err}</Callout></div>}
      <SimpleTable
        rows={[...reports].reverse()}
        empty={<EmptyState title="No reports">Generate a draft once analyses are complete. Finalisation requires a recorded human review decision and a different person from the author.</EmptyState>}
        columns={[
          { key: "v", header: "Version", render: (r: Report) => <span className="font-mono">v{r.version}</span> },
          { key: "status", header: "Status", render: (r: Report) => <Badge tone={r.status === "final" ? "ok" : r.status === "superseded" ? "slate" : "accent"} dot>{r.status}</Badge> },
          { key: "gen", header: "Generated", render: (r: Report) => <span className="text-xs text-muted">{fmtDate(r.generated_at)}</span> },
          { key: "hash", header: "JSON SHA-256", render: (r: Report) => <Hash value={r.json_sha256} short /> },
          {
            key: "integrity",
            header: "Integrity",
            render: (r: Report) => verify[r.id] ? <Badge tone={verify[r.id].intact ? "ok" : "danger"}>{verify[r.id].intact ? "intact & reproducible" : "TAMPERING DETECTED"}</Badge> : <button className="text-xs text-accent hover:underline" onClick={() => api(`/reports/${r.id}/verify`, { method: "POST" }).then((v) => setVerify((s) => ({ ...s, [r.id]: v })))}>Verify</button>,
          },
          {
            key: "actions",
            header: "",
            render: (r: Report) => (
              <div className="flex flex-wrap justify-end gap-1.5">
                <Button size="sm" variant="ghost" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => download(`/reports/${r.id}/pdf`, `report-v${r.version}.pdf`)}>PDF</Button>
                <Button size="sm" variant="ghost" icon={<FileJson className="h-3.5 w-3.5" />} onClick={() => download(`/reports/${r.id}/json`, `report-v${r.version}.json`)}>JSON</Button>
                {r.status === "draft" && can("report.finalize") && <Button size="sm" onClick={() => run(() => api(`/reports/${r.id}/finalize`, { method: "POST" }))}>Finalise</Button>}
                {r.status === "final" && can("report.generate") && <Button size="sm" onClick={() => setCorrecting(r)}>Correct</Button>}
              </div>
            ),
          },
        ]}
      />
      <Dialog open={!!correcting} onClose={() => setCorrecting(null)} title={`Correct report v${correcting?.version}`} footer={<Button variant="primary" disabled={reason.length < 10} onClick={() => run(async () => { await api(`/reports/${correcting!.id}/corrections`, { json: { reason } }); setCorrecting(null); setReason(""); })}>Create corrected version</Button>}>
        <p className="text-sm text-muted">The finalised version is preserved and marked superseded once the correction is finalised.</p>
        <Field label="Reason for correction"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Dialog>
    </Panel>
  );
}

function AppealsTab({ inv, appeals, onChange }: { inv: Investigation; appeals: any[]; onChange: () => void }) {
  const { can } = useAuth();
  const [grounds, setGrounds] = React.useState("");
  const [behalf, setBehalf] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const [resolving, setResolving] = React.useState<any | null>(null);
  const [status, setStatus] = React.useState("under_review");
  const [resolution, setResolution] = React.useState("");
  const submit = async () => {
    setErr(null);
    try {
      await api(`/investigations/${inv.id}/appeals`, { json: { grounds, on_behalf_of: behalf || null } });
      setGrounds("");
      setBehalf("");
      onChange();
    } catch (e) {
      setErr(errMsg(e));
    }
  };
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="Submit an appeal or correction request" icon={<Gavel className="h-4 w-4" />}>
        {can("appeal.submit") ? (
          <div className="space-y-3">
            <Field label="On behalf of (optional)" hint="Use a role or reference rather than personal details where possible."><input className="input" value={behalf} onChange={(e) => setBehalf(e.target.value)} /></Field>
            <Field label="Grounds" hint="At least 20 characters."><Textarea value={grounds} onChange={(e) => setGrounds(e.target.value)} className="min-h-[120px]" /></Field>
            {err && <Callout tone="danger">{err}</Callout>}
            <Button variant="primary" disabled={grounds.length < 20} onClick={submit}>Submit appeal</Button>
          </div>
        ) : (
          <p className="text-sm text-muted">Your role cannot submit appeals.</p>
        )}
      </Panel>
      <Panel title="Appeals">
        <ul className="space-y-3">
          {appeals.map((a) => (
            <li key={a.id} className="rounded-lg border border-line/70 bg-bg/40 p-4">
              <div className="flex items-center gap-2 text-xs">
                <Badge tone={{ open: "accent", under_review: "violet", upheld: "ok", corrected: "ok", rejected: "slate" }[a.status as string] ?? "slate"} dot>{humanize(a.status)}</Badge>
                <span className="text-muted">{fmtDate(a.created_at)}</span>
                {a.on_behalf_of && <span className="text-muted">· {a.on_behalf_of}</span>}
                {can("appeal.resolve") && !["upheld", "corrected", "rejected"].includes(a.status) && <button className="ml-auto text-accent hover:underline" onClick={() => setResolving(a)}>Resolve</button>}
              </div>
              <p className="mt-2 text-sm text-ink/90">{a.grounds}</p>
              {a.resolution && <p className="mt-2 border-t border-line/50 pt-2 text-sm text-muted">Resolution: {a.resolution}</p>}
            </li>
          ))}
          {!appeals.length && <p className="text-sm text-muted">No appeals.</p>}
        </ul>
      </Panel>
      <Dialog open={!!resolving} onClose={() => setResolving(null)} title="Resolve appeal" footer={<Button variant="primary" disabled={resolution.length < 10} onClick={async () => { try { await api(`/investigations/${inv.id}/appeals/${resolving.id}/resolve`, { json: { status, resolution } }); setResolving(null); setResolution(""); onChange(); } catch (e) { setErr(errMsg(e)); } }}>Record outcome</Button>}>
        <Field label="Outcome">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["under_review", "upheld", "corrected", "rejected"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
        </Field>
        <Field label="Resolution"><Textarea value={resolution} onChange={(e) => setResolution(e.target.value)} /></Field>
      </Dialog>
    </div>
  );
}
