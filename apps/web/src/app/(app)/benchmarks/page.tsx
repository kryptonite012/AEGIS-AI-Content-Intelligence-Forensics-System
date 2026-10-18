"use client";

import type { BenchmarkRun, Dataset, MethodInfo } from "@aegis/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, FlaskConical, Play, Plus, Scale, Upload } from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { JobStatusBadge, ResultKindBadge } from "@/components/badges";
import { Bars, PrChart, RocChart, SimpleLines } from "@/components/charts";
import { Badge, Button, Callout, Dialog, EmptyState, ErrorBlock, Field, Hash, Input, KV, LoadingBlock, PageHeader, Panel, Select, SimpleTable, Stat, Tabs, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { RESULT_KIND, cx, fmtDate, fmtNum, fmtPct, humanize } from "@/lib/format";

function RunDetail({ run }: { run: BenchmarkRun }) {
  const o = run.metrics?.overall ?? {};
  const m = o.metrics;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <ResultKindBadge value={run.result_kind} />
        <JobStatusBadge value={run.status} />
        <span className="font-mono text-xs text-muted">{run.method_id} v{run.method_version}</span>
        <span className="text-xs text-muted">· {fmtDate(run.finished_at ?? run.created_at)}</span>
      </div>
      <Callout tone={run.result_kind === "locally_measured" ? "ok" : "warn"}>{RESULT_KIND[run.result_kind]?.note}{run.source_citation && ` Source: ${run.source_citation}`}</Callout>
      {run.error && <Callout tone="danger" title="Run failed">{run.error}</Callout>}
      {o.error && <Callout tone="warn">{o.error}</Callout>}
      {o.auroc != null && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Stat label="AUROC" value={fmtNum(o.auroc)} hint={o.auroc_ci ? `95% CI ${fmtNum(o.auroc_ci.low)}–${fmtNum(o.auroc_ci.high)} (bootstrap)` : undefined} />
            <Stat label="Test samples" value={o.n} tone="cyan" hint={`${run.metrics.not_scored ?? 0} not scored`} />
            <Stat label="Threshold" value={fmtNum(run.metrics.threshold, 4)} tone="violet" hint={humanize(run.metrics.threshold_source)} />
            <Stat label="TPR / sensitivity" value={fmtPct(m?.tpr?.value)} tone="ok" hint={m?.tpr?.interval ? `CI ${fmtPct(m.tpr.interval.low)}–${fmtPct(m.tpr.interval.high)} (exact)` : "needs a threshold"} />
            <Stat label="FPR" value={fmtPct(m?.fpr?.value, 2)} tone="danger" hint={m?.fpr?.interval ? `CI ${fmtPct(m.fpr.interval.low, 2)}–${fmtPct(m.fpr.interval.high, 2)} (exact)` : "needs a threshold"} />
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <Panel title="ROC curve" subtitle="Strict-FPR region matters most for screening"><RocChart points={o.roc ?? []} /></Panel>
            <Panel title="Precision–recall"><PrChart points={o.pr ?? []} /></Panel>
          </div>
          <Panel title="Sensitivity at strict false-positive operating points">
            <SimpleTable
              rows={(o.operating_points ?? []).map((x: any) => ({ id: x.target_fpr, ...x }))}
              columns={[
                { key: "t", header: "Target FPR", render: (x) => fmtPct(x.target_fpr, 1) },
                { key: "thr", header: "Threshold", render: (x) => fmtNum(x.threshold, 4) },
                { key: "afpr", header: "Achieved FPR", render: (x) => fmtPct(x.achieved_fpr, 2) },
                { key: "tpr", header: "TPR", render: (x) => fmtPct(x.tpr?.value) },
                { key: "neg", header: "Negatives", render: (x) => `${x.negatives} (need ≥ ${x.min_negatives_required})` },
                { key: "e", header: "Status", render: (x) => <Badge tone={x.estimable ? "ok" : "warn"}>{x.estimable ? "estimable" : "not validated"}</Badge> },
              ]}
            />
            <p className="mt-3 text-xs text-muted">A 0.1% FPR cannot be claimed from a sample that cannot estimate it: with zero false positives, about 3/FPR negatives are needed for a 95% bound.</p>
          </Panel>
          {m && (
            <Panel title="Confusion matrix at the selected threshold" subtitle="Precision/NPV reflect this sample's class balance, not a deployment population">
              <div className="grid gap-6 md:grid-cols-[260px_1fr]">
                <div className="grid grid-cols-2 gap-2 text-center text-sm">
                  {[["TP", m.confusion.tp, "ok"], ["FP", m.confusion.fp, "danger"], ["FN", m.confusion.fn, "warn"], ["TN", m.confusion.tn, "slate"]].map(([k, v, t]) => (
                    <div key={k as string} className={cx("rounded-lg border py-4", { ok: "border-ok/40", danger: "border-danger/40", warn: "border-warn/40", slate: "border-line" }[t as string])}>
                      <div className="label">{k as string}</div>
                      <div className="mt-1 text-xl font-semibold tabular-nums">{v as number}</div>
                    </div>
                  ))}
                </div>
                <KV cols={3} items={[["Specificity", fmtPct(m.tnr?.value)], ["FNR", fmtPct(m.fnr?.value)], ["Sample precision", fmtPct(m.precision?.value)], ["NPV (sample)", fmtPct(m.npv?.value)], ["F1", fmtNum(m.f1)], ["Accuracy", fmtPct(m.accuracy?.value)]]} />
              </div>
              {m.warnings?.map((w: string) => <p key={w} className="mt-2 text-xs text-warn/90">{w}</p>)}
            </Panel>
          )}
          {o.calibration && (
            <Panel title="Calibration"><KV items={[["Brier score", fmtNum(o.calibration.brier)], ["Expected calibration error", fmtNum(o.calibration.ece)]]} /></Panel>
          )}
          {!!Object.keys(run.metrics.robustness ?? {}).length && (
            <Panel title="Robustness to documented transformations" subtitle="Defensive measurement only — not an evasion service">
              <Bars data={[{ transform: "original", auroc: o.auroc }, ...Object.entries(run.metrics.robustness).map(([k, v]: any) => ({ transform: humanize(k), auroc: v.auroc }))]} x="transform" bars={[{ key: "auroc", name: "AUROC" }]} colorByIndex />
            </Panel>
          )}
          {!!o.subgroups?.length && (
            <Panel title="Subgroup error rates" subtitle="From evaluation-data fields only; small groups suppressed">
              <SimpleTable rows={o.subgroups.map((g: any) => ({ id: g.group, ...g }))} columns={[
                { key: "group", header: "Group" },
                { key: "n", header: "n", render: (g) => (g.suppressed ? "suppressed" : g.n) },
                { key: "fpr", header: "FPR", render: (g) => (g.suppressed ? "—" : `${fmtPct(g.fpr.value, 1)} (${g.fpr.numerator}/${g.fpr.denominator})`) },
                { key: "fnr", header: "FNR", render: (g) => (g.suppressed ? "—" : `${fmtPct(g.fnr.value, 1)} (${g.fnr.numerator}/${g.fnr.denominator})`) },
              ]} />
            </Panel>
          )}
        </>
      )}
      <Panel title="Run manifest" subtitle="Everything needed to reproduce this run">
        <pre className="max-h-80 overflow-auto rounded-lg bg-bg/70 p-3 font-mono text-[11px] text-ink/80">{JSON.stringify({ config: run.config, manifest: run.manifest }, null, 2)}</pre>
      </Panel>
    </div>
  );
}

function ThresholdExplorer({ runs }: { runs: BenchmarkRun[] }) {
  const usable = runs.filter((r) => r.status === "completed" && r.metrics?.overall?.auroc != null && !r.method_id.startsWith("imported"));
  const [runId, setRunId] = React.useState(usable[0]?.id ?? "");
  const [prev, setPrev] = React.useState(0.05);
  const [pop, setPop] = React.useState(10000);
  const { data, error, isFetching } = useQuery({
    queryKey: ["threshold", runId, prev, pop],
    queryFn: () => api<any>("/evaluation/threshold-explorer", { json: { benchmark_run_id: runId, deployment_prevalence: prev, population_size: pop } }),
    enabled: !!runId,
  });
  if (!usable.length) return <EmptyState title="No completed runs with scores">Run a benchmark first.</EmptyState>;
  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Benchmark run"><Select value={runId} onChange={(e) => setRunId(e.target.value)}>{usable.map((r) => <option key={r.id} value={r.id}>{r.method_id} · {RESULT_KIND[r.result_kind].label} · {fmtDate(r.created_at)}</option>)}</Select></Field>
        <Field label="Deployment prevalence"><Input type="number" min={0} max={1} step={0.005} value={prev} onChange={(e) => setPrev(Number(e.target.value))} /></Field>
        <Field label="Population screened"><Input type="number" min={1} value={pop} onChange={(e) => setPop(Number(e.target.value))} /></Field>
      </div>
      {error && <ErrorBlock error={error} />}
      {data && (
        <>
          <SimpleLines
            data={data.rows.map((r: any) => ({ threshold: r.threshold, TPR: r.tpr, FPR: r.fpr, "deployment PPV": r.deployment_ppv }))}
            x="threshold"
            lines={[{ key: "TPR" }, { key: "FPR" }, { key: "deployment PPV", dashed: true }]}
            xLabel="decision threshold (flag if score ≥ threshold)"
            yDomain={[0, 1]}
          />
          <SimpleTable
            dense
            rows={data.rows.filter((_: any, i: number) => i % 2 === 0).map((r: any) => ({ id: r.threshold, ...r }))}
            columns={[
              { key: "threshold", header: "Threshold", render: (r) => fmtNum(r.threshold, 4) },
              { key: "tpr", header: "TPR", render: (r) => fmtPct(r.tpr) },
              { key: "fpr", header: "FPR", render: (r) => fmtPct(r.fpr, 2) },
              { key: "ppv", header: "Deployment PPV", render: (r) => fmtPct(r.deployment_ppv) },
              { key: "vol", header: "Review volume", render: (r) => Math.round(r.expected_review_volume ?? 0).toLocaleString() },
              { key: "ff", header: "Expected false accusations", render: (r) => <span className="text-danger">{Math.round(r.expected_false_flags ?? 0).toLocaleString()}</span> },
              { key: "miss", header: "Missed synthetic items", render: (r) => <span className="text-warn">{Math.round(r.expected_missed_ai ?? 0).toLocaleString()}</span> },
            ]}
          />
          <Callout tone="slate">{data.statement} Based on {data.n} labelled scores ({data.negatives} negatives){isFetching ? " · updating…" : ""}.</Callout>
        </>
      )}
    </div>
  );
}

function Fairness({ runs }: { runs: BenchmarkRun[] }) {
  const usable = runs.filter((r) => r.status === "completed" && r.metrics?.threshold != null);
  const [runId, setRunId] = React.useState(usable[0]?.id ?? "");
  const [min, setMin] = React.useState(10);
  const { data, error } = useQuery({ queryKey: ["fairness", runId, min], queryFn: () => api<any>(`/evaluation/fairness/${runId}?min_group_size=${min}`), enabled: !!runId });
  if (!usable.length) return <EmptyState title="No runs with a validation-selected threshold">Fairness evaluation needs a threshold chosen on a separate validation split.</EmptyState>;
  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Benchmark run"><Select value={runId} onChange={(e) => setRunId(e.target.value)}>{usable.map((r) => <option key={r.id} value={r.id}>{r.method_id} · {RESULT_KIND[r.result_kind].label}</option>)}</Select></Field>
        <Field label="Suppress groups smaller than"><Input type="number" min={1} value={min} onChange={(e) => setMin(Number(e.target.value))} /></Field>
      </div>
      {error && <ErrorBlock error={error} />}
      {data && (
        <>
          <Bars data={data.groups.filter((g: any) => !g.suppressed).map((g: any) => ({ group: g.group, FPR: g.fpr.value, FNR: g.fnr.value }))} x="group" bars={[{ key: "FPR" }, { key: "FNR" }]} />
          <SimpleTable rows={data.groups.map((g: any) => ({ id: g.group, ...g }))} columns={[
            { key: "group", header: "Group" },
            { key: "n", header: "n", render: (g) => (g.suppressed ? <Badge>suppressed</Badge> : g.n) },
            { key: "fpr", header: "FPR (exact 95% CI)", render: (g) => (g.suppressed ? "—" : `${fmtPct(g.fpr.value)} [${fmtPct(g.fpr.interval?.low)}–${fmtPct(g.fpr.interval?.high)}]`) },
            { key: "fnr", header: "FNR (exact 95% CI)", render: (g) => (g.suppressed ? "—" : `${fmtPct(g.fnr.value)} [${fmtPct(g.fnr.interval?.low)}–${fmtPct(g.fnr.interval?.high)}]`) },
          ]} />
          <Callout tone="slate">{data.statement}</Callout>
        </>
      )}
    </div>
  );
}

function DatasetDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = React.useState<File | null>(null);
  const [v, setV] = React.useState({ name: "", version: "1.0", provenance: "", license: "", consent_basis: "", documentation: "", is_synthetic: false });
  const [err, setErr] = React.useState<string | null>(null);
  const submit = async () => {
    if (!file) return;
    const f = new FormData();
    f.append("file", file);
    Object.entries(v).forEach(([k, val]) => f.append(k, String(val)));
    try {
      await api("/benchmarks/datasets", { form: f });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="Register evaluation dataset" wide footer={<Button variant="primary" onClick={submit} disabled={!file}>Register</Button>}>
      <Callout tone="slate">JSONL, one object per line: <code className="hash">{'{"id","text","label":0|1,"split":"train|validation|test","group","generator","domain","language","transform"}'}</code>. Provenance, licence and consent are required. Cross-split duplicates are detected and excluded from evaluation.</Callout>
      <Field label="File"><input type="file" accept=".jsonl,application/x-ndjson,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="input" /></Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name"><Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
        <Field label="Version"><Input value={v.version} onChange={(e) => setV({ ...v, version: e.target.value })} /></Field>
        <Field label="Licence"><Input value={v.license} onChange={(e) => setV({ ...v, license: e.target.value })} /></Field>
        <label className="flex items-center gap-2 pt-6 text-sm"><input type="checkbox" checked={v.is_synthetic} onChange={(e) => setV({ ...v, is_synthetic: e.target.checked })} /> Synthetic data (results labelled simulated)</label>
      </div>
      <Field label="Provenance"><Textarea value={v.provenance} onChange={(e) => setV({ ...v, provenance: e.target.value })} /></Field>
      <Field label="Consent / lawful basis"><Textarea value={v.consent_basis} onChange={(e) => setV({ ...v, consent_basis: e.target.value })} /></Field>
      <Field label="Documentation (dataset card)"><Textarea value={v.documentation} onChange={(e) => setV({ ...v, documentation: e.target.value })} /></Field>
      {err && <Callout tone="danger">{err}</Callout>}
    </Dialog>
  );
}

function NewRunDialog({ open, onClose, datasets }: { open: boolean; onClose: () => void; datasets: Dataset[] }) {
  const qc = useQueryClient();
  const methods = useQuery({ queryKey: ["detectors"], queryFn: () => api<MethodInfo[]>("/detectors") });
  const textMethods = (methods.data ?? []).filter((m) => m.modalities.includes("text") && ["statistical_inference", "verified_watermark"].includes(m.evidence_class));
  const [v, setV] = React.useState({ method_id: "", dataset_id: "", target_fpr: 0.01, holdout_field: "", holdout_values: "" });
  const [err, setErr] = React.useState<string | null>(null);
  const submit = async () => {
    try {
      await api("/benchmarks/runs", { json: { method_id: v.method_id, dataset_id: v.dataset_id, target_fpr: v.target_fpr, holdout_field: v.holdout_field || null, holdout_values: v.holdout_values ? v.holdout_values.split(",").map((s) => s.trim()) : [] } });
      qc.invalidateQueries({ queryKey: ["bench-runs"] });
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="New benchmark run" footer={<Button variant="primary" onClick={submit} disabled={!v.method_id || !v.dataset_id}>Queue run</Button>}>
      <Field label="Method"><Select value={v.method_id} onChange={(e) => setV({ ...v, method_id: e.target.value })}><option value="">Select…</option>{textMethods.map((m) => <option key={m.id} value={m.id} disabled={!m.available}>{m.name}{m.available ? "" : " (unavailable)"}</option>)}</Select></Field>
      <Field label="Dataset"><Select value={v.dataset_id} onChange={(e) => setV({ ...v, dataset_id: e.target.value })}><option value="">Select…</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name}@{d.version}</option>)}</Select></Field>
      <Field label="Target FPR for threshold selection (on the validation split)"><Input type="number" step={0.001} value={v.target_fpr} onChange={(e) => setV({ ...v, target_fpr: Number(e.target.value) })} /></Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Held-out evaluation" hint="Evaluate only on unseen values of this field"><Select value={v.holdout_field} onChange={(e) => setV({ ...v, holdout_field: e.target.value })}><option value="">None</option><option value="generator">Generator</option><option value="domain">Domain</option><option value="language">Language</option></Select></Field>
        <Field label="Held-out values (comma-separated)"><Input value={v.holdout_values} onChange={(e) => setV({ ...v, holdout_values: e.target.value })} /></Field>
      </div>
      {err && <Callout tone="danger">{err}</Callout>}
    </Dialog>
  );
}

function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = React.useState<File | null>(null);
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState("locally_measured");
  const [citation, setCitation] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const submit = async () => {
    const f = new FormData();
    f.append("file", file!);
    f.append("name", name);
    f.append("result_kind", kind);
    if (citation) f.append("citation", citation);
    try {
      await api("/benchmarks/imported-scores", { form: f });
      qc.invalidateQueries({ queryKey: ["bench-runs"] });
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="Import labelled scores" footer={<Button variant="primary" onClick={submit} disabled={!file || !name}>Import</Button>}>
      <Callout tone="slate">CSV with columns <code className="hash">label,score[,group,transform]</code>. AEGIS computes metrics from the supplied labels and scores; it does not run the detector.</Callout>
      <Field label="File"><input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="input" /></Field>
      <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Result kind"><Select value={kind} onChange={(e) => setKind(e.target.value)}>{["locally_measured", "published", "reproduced", "vendor_reported"].map((k) => <option key={k} value={k}>{RESULT_KIND[k].label}</option>)}</Select></Field>
      {kind !== "locally_measured" && <Field label="Citation / source" hint="Required for published, reproduced or vendor-reported numbers."><Input value={citation} onChange={(e) => setCitation(e.target.value)} /></Field>}
      {err && <Callout tone="danger">{err}</Callout>}
    </Dialog>
  );
}

type Tab = "runs" | "datasets" | "threshold" | "fairness";

export default function BenchmarkLabPage() {
  const { can } = useAuth();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [tab, setTab] = React.useState<Tab>("runs");
  const [selected, setSelected] = React.useState<string | null>(params.get("run"));
  const [dialog, setDialog] = React.useState<null | "dataset" | "run" | "import">(null);
  const runs = useQuery({ queryKey: ["bench-runs"], queryFn: () => api<BenchmarkRun[]>("/benchmarks/runs"), refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 3000 : false) });
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => api<Dataset[]>("/benchmarks/datasets") });
  const builtin = useMutation({
    mutationFn: () => api<BenchmarkRun>("/benchmarks/reference-watermark", { method: "POST" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["bench-runs"] });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      setSelected(r.id);
    },
  });
  const sel = runs.data?.find((r) => r.id === selected) ?? runs.data?.[0];
  return (
    <>
      <PageHeader
        eyebrow="Reproducible evaluation"
        title={<span className="flex items-center gap-3"><FlaskConical className="h-6 w-6 text-accent" /> Benchmark laboratory</span>}
        description="Versioned datasets with provenance and licence records, fixed seeds, held-out evaluation and run manifests. Published, reproduced, locally measured, simulated and vendor-reported results are always kept apart."
        actions={can("benchmark.run") && (
          <>
            <Button onClick={() => builtin.mutate()} loading={builtin.isPending} icon={<Play className="h-4 w-4" />}>Run built-in simulated benchmark</Button>
            <Button onClick={() => setDialog("import")} icon={<Upload className="h-4 w-4" />}>Import scores</Button>
            <Button variant="primary" onClick={() => setDialog("run")} icon={<Plus className="h-4 w-4" />}>New run</Button>
          </>
        )}
      />
      {builtin.error && <div className="mb-4"><ErrorBlock error={builtin.error} /></div>}
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "runs", label: "Runs", count: runs.data?.length }, { id: "datasets", label: "Datasets", count: datasets.data?.length }, { id: "threshold", label: "Threshold explorer" }, { id: "fairness", label: "Fairness" }]} />
      <div className="mt-6">
        {tab === "runs" && (runs.isLoading ? <LoadingBlock /> : !runs.data?.length ? (
          <EmptyState title="No benchmark runs" icon={<FlaskConical className="h-5 w-5" />}>Run the built-in simulated benchmark of the reference watermark verifier, register a labelled dataset, or import scores.</EmptyState>
        ) : (
          <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
            <Panel title="Runs" bodyClassName="p-2">
              <ul className="space-y-1">
                {runs.data.map((r) => (
                  <li key={r.id}>
                    <button onClick={() => setSelected(r.id)} className={cx("w-full rounded-lg px-3 py-2.5 text-left", sel?.id === r.id ? "bg-accent/10 ring-1 ring-accent/30" : "hover:bg-raised/60")}>
                      <div className="truncate font-mono text-xs">{r.method_id}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5"><ResultKindBadge value={r.result_kind} /><JobStatusBadge value={r.status} /></div>
                      <div className="mt-1 text-[11px] text-muted">AUROC {fmtNum(r.metrics?.overall?.auroc)} · {fmtDate(r.created_at)}</div>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <div className="min-w-0">{sel && <RunDetail run={sel} />}</div>
          </div>
        ))}
        {tab === "datasets" && (
          <Panel title="Registered datasets" icon={<Database className="h-4 w-4" />} actions={can("dataset.register") && <Button size="sm" onClick={() => setDialog("dataset")} icon={<Plus className="h-3.5 w-3.5" />}>Register dataset</Button>}>
            <SimpleTable rows={datasets.data ?? []} columns={[
              { key: "name", header: "Dataset", render: (d: Dataset) => <span className="font-medium">{d.name}<span className="ml-1 font-mono text-xs text-muted">@{d.version}</span></span> },
              { key: "syn", header: "Kind", render: (d: Dataset) => <Badge tone={d.is_synthetic ? "warn" : "ok"}>{d.is_synthetic ? "synthetic" : "real"}</Badge> },
              { key: "n", header: "Samples", render: (d: Dataset) => d.n_samples },
              { key: "splits", header: "Splits", render: (d: Dataset) => <span className="text-xs text-muted">{Object.entries(d.splits).map(([k, v]) => `${k} ${v}`).join(" · ")}</span> },
              { key: "dup", header: "Cross-split duplicates", render: (d: Dataset) => <Badge tone={d.duplicate_report.cross_split_duplicates ? "warn" : "ok"}>{d.duplicate_report.cross_split_duplicates ?? 0}</Badge> },
              { key: "lic", header: "Licence", render: (d: Dataset) => <span className="text-xs">{d.license}</span> },
              { key: "sha", header: "SHA-256", render: (d: Dataset) => <Hash value={d.sha256} short /> },
            ]} />
          </Panel>
        )}
        {tab === "threshold" && <Panel title="Threshold explorer" subtitle="Trade-off between catching synthetic content and avoiding false accusations" icon={<Scale className="h-4 w-4" />}><ThresholdExplorer runs={runs.data ?? []} /></Panel>}
        {tab === "fairness" && <Panel title="Fairness laboratory" subtitle="Subgroup false-positive and false-negative rates with uncertainty"><Fairness runs={runs.data ?? []} /></Panel>}
      </div>
      <DatasetDialog open={dialog === "dataset"} onClose={() => setDialog(null)} />
      <NewRunDialog open={dialog === "run"} onClose={() => setDialog(null)} datasets={datasets.data ?? []} />
      <ImportDialog open={dialog === "import"} onClose={() => setDialog(null)} />
    </>
  );
}
