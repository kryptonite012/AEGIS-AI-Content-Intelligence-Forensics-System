"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Calculator, FlaskRound, Microscope, Play } from "lucide-react";
import * as React from "react";

import { Bars, PpvCurve, SimpleLines } from "@/components/charts";
import { Badge, Button, Callout, ErrorBlock, Field, Input, KV, PageHeader, Panel, Select, SimpleTable, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { cx, fmtNum, fmtPct, humanize } from "@/lib/format";

const BORDER: Record<string, string> = { ok: "border-ok/30", danger: "border-danger/30", warn: "border-warn/30", slate: "border-line" };

type Source = "assumed" | "measured" | "published" | "vendor_reported" | "simulated";

function RateInput({ label, value, onChange, source, onSource }: { label: string; value: number; onChange: (v: number) => void; source: Source; onSource: (s: Source) => void }) {
  return (
    <div className="rounded-lg border border-line/70 bg-bg/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{label}</span>
        <span className="font-mono text-sm tabular-nums text-accent">{fmtPct(value, value < 0.01 ? 2 : 1)}</span>
      </div>
      <input type="range" min={0} max={1} step={0.001} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 w-full accent-[rgb(59,130,246)]" aria-label={label} />
      <div className="mt-2 grid grid-cols-[1fr_140px] gap-2">
        <Input type="number" min={0} max={1} step={0.001} value={value} onChange={(e) => onChange(Math.min(1, Math.max(0, Number(e.target.value))))} aria-label={`${label} value`} className="h-8 py-1 text-xs" />
        <Select value={source} onChange={(e) => onSource(e.target.value as Source)} className="h-8 py-1 text-xs" aria-label={`${label} source`}>
          <option value="assumed">Assumed</option>
          <option value="measured">Measured</option>
          <option value="published">Published</option>
          <option value="vendor_reported">Vendor-reported</option>
          <option value="simulated">Simulated</option>
        </Select>
      </div>
    </div>
  );
}

function PpvCalculator() {
  const [tpr, setTpr] = React.useState(0.9);
  const [fpr, setFpr] = React.useState(0.05);
  const [prev, setPrev] = React.useState(0.05);
  const [n, setN] = React.useState(10000);
  const [src, setSrc] = React.useState<Record<string, Source>>({ tpr: "assumed", fpr: "assumed", prevalence: "assumed" });
  const body = { tpr, fpr, prevalence: prev, sample_size: n, tpr_source: src.tpr, fpr_source: src.fpr, prevalence_source: src.prevalence };
  const { data, error } = useQuery({ queryKey: ["ppv", body], queryFn: () => api<any>("/evaluation/ppv", { json: body }), placeholderData: (p) => p });
  const preset = () => {
    setTpr(0.9);
    setFpr(0.05);
    setPrev(0.05);
    setN(10000);
  };
  return (
    <Panel title="Base-rate calculator" subtitle="Bayes' rule: how many flags are correct in a given screening population?" icon={<Calculator className="h-4 w-4" />} actions={<Button size="sm" variant="ghost" onClick={preset}>Paper example (90% / 5% / 5%)</Button>}>
      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <div className="space-y-3">
          <RateInput label="Sensitivity (TPR)" value={tpr} onChange={setTpr} source={src.tpr} onSource={(s) => setSrc({ ...src, tpr: s })} />
          <RateInput label="False-positive rate (FPR)" value={fpr} onChange={setFpr} source={src.fpr} onSource={(s) => setSrc({ ...src, fpr: s })} />
          <RateInput label="Prevalence of AI content" value={prev} onChange={setPrev} source={src.prevalence} onSource={(s) => setSrc({ ...src, prevalence: s })} />
          <Field label="Items screened"><Input type="number" min={1} value={n} onChange={(e) => setN(Math.max(1, Number(e.target.value)))} /></Field>
        </div>
        <div className="min-w-0">
          {error && <ErrorBlock error={error} />}
          {data && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Stat label="PPV — flags that are AI" value={fmtPct(data.ppv)} tone="violet" hint="under the stated assumptions" />
                <Stat label="False flags per true flag" value={fmtNum(data.false_flags_per_true_flag, 2)} tone="danger" />
                <Stat label="NPV" value={fmtPct(data.npv, 2)} tone="ok" />
                <Stat label="Expected flags" value={Math.round(data.expected_flags ?? 0).toLocaleString()} tone="accent" hint={`of ${n.toLocaleString()} items`} />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-4">
                {[
                  ["Correct positive flags", data.expected_true_positives, "ok"],
                  ["False positive flags", data.expected_false_positives, "danger"],
                  ["Missed AI-generated items", data.expected_false_negatives, "warn"],
                  ["Correct negatives", data.expected_true_negatives, "slate"],
                ].map(([l, v, t]) => (
                  <div key={l as string} className={cx("rounded-lg border px-3 py-2.5", BORDER[t as string])}>
                    <div className="label">{l as string}</div>
                    <div className="mt-1 text-lg font-semibold tabular-nums">{Math.round(v as number).toLocaleString()}</div>
                  </div>
                ))}
              </div>
              <div className="mt-5">
                <PpvCurve series={[{ name: "PPV", points: data.sensitivity }, { name: "NPV", points: data.sensitivity.map((r: any) => ({ prevalence: r.prevalence, ppv: r.npv })) }]} marker={prev} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                {Object.entries(data.sources).map(([k, v]) => <Badge key={k} tone={v === "measured" ? "ok" : v === "assumed" ? "slate" : "warn"}>{k}: {v as string}</Badge>)}
              </div>
              <p className="mt-3 font-mono text-[11px] text-muted">{data.formula}</p>
              <Callout tone="slate">{data.statement}</Callout>
            </>
          )}
        </div>
      </div>
    </Panel>
  );
}

const EXPERIMENTS: { id: string; title: string; defaults: Record<string, number>; params: string[] }[] = [
  { id: "exp1_base_rate", title: "1 · Base-rate effects", defaults: { tpr: 0.9, fpr: 0.05, prevalence: 0.05 }, params: ["tpr", "fpr", "prevalence"] },
  { id: "exp2_subgroup", title: "2 · Subgroup error concentration", defaults: {}, params: [] },
  { id: "exp3_corroboration", title: "3 · Corroborating evidence", defaults: { tpr1: 0.9, fpr1: 0.05, tpr2: 0.8, fpr2: 0.05 }, params: ["tpr1", "fpr1", "tpr2", "fpr2"] },
  { id: "exp4_auroc_strict_fpr", title: "4 · AUROC vs strict operating points", defaults: { n_neg: 2000 }, params: ["n_neg"] },
  { id: "exp5_watermark_length_entropy", title: "5 · Watermark length & entropy", defaults: { trials: 20 }, params: ["trials"] },
  { id: "exp6_watermark_robustness", title: "6 · Watermark robustness", defaults: { trials: 20, length: 200 }, params: ["trials", "length"] },
  { id: "exp7_threshold_selection", title: "7 · Threshold selection", defaults: { gamma: 0.25 }, params: ["gamma"] },
  { id: "exp8_strength_distortion", title: "8 · Watermark strength vs distortion", defaults: { trials: 20 }, params: ["trials"] },
  { id: "exp9_fpr_calibration", title: "9 · Exact vs approximate FPR", defaults: { gamma: 0.25 }, params: ["gamma"] },
];

function pivot(rows: any[], x: string, series: string, y: string) {
  const xs = Array.from(new Set(rows.map((r) => r[x]))).sort((a, b) => a - b);
  const ss = Array.from(new Set(rows.map((r) => r[series])));
  return { data: xs.map((xv) => Object.fromEntries([[x, xv], ...ss.map((s) => [`${series}=${s}`, rows.find((r) => r[x] === xv && r[series] === s)?.[y] ?? null])])), lines: ss.map((s) => ({ key: `${series}=${s}` })) };
}

function ExperimentResult({ r }: { r: any }) {
  const res = r.results;
  switch (r.id) {
    case "exp1_base_rate": {
      const ex = res.illustrative_example;
      return (
        <div className="space-y-4">
          <KV cols={3} items={[["PPV at stated prevalence", fmtPct(ex.ppv)], ["False flags per true flag", fmtNum(ex.false_flags_per_true_flag, 2)], ["Expected flags / 10,000", Math.round(ex.expected_flags)]]} />
          <PpvCurve series={Object.entries(res.curves).map(([name, pts]) => ({ name, points: pts as any }))} marker={r.config.prevalence} />
        </div>
      );
    }
    case "exp2_subgroup":
      return <Bars data={res.map((g: any) => ({ group: g.group, "population share": g.population_share, "share of false flags": g.false_flag_share }))} x="group" bars={[{ key: "population share" }, { key: "share of false flags" }]} />;
    case "exp3_corroboration":
      return (
        <div className="space-y-3">
          <KV cols={3} items={[["Assumed joint TPR", fmtPct(res.assumption_based.tpr)], ["Assumed joint FPR", fmtPct(res.assumption_based.fpr, 2)], ["Assumption", res.assumption_based.assumption]]} />
          <SimpleLines data={res.simulated.map((s: any) => ({ rho: s.within_class_correlation, "empirical joint FPR": s.empirical_joint_fpr, "independence assumption": s.assumed_independent_fpr }))} x="rho" lines={[{ key: "empirical joint FPR" }, { key: "independence assumption", dashed: true }]} xLabel="within-class correlation between detectors" />
        </div>
      );
    case "exp4_auroc_strict_fpr":
      return (
        <SimpleTable
          rows={res.flatMap((d: any) => d.operating_points.map((o: any) => ({ id: d.detector + o.target_fpr, detector: d.detector, auroc: d.auroc, ...o })))}
          dense
          columns={[
            { key: "detector", header: "Simulated detector", render: (x) => humanize(x.detector) },
            { key: "auroc", header: "AUROC", render: (x) => fmtNum(x.auroc) },
            { key: "t", header: "Target FPR", render: (x) => fmtPct(x.target_fpr, 1) },
            { key: "tpr", header: "TPR at target", render: (x) => fmtPct(x.tpr?.value) },
            { key: "ci", header: "TPR 95% CI", render: (x) => (x.tpr?.interval ? `${fmtPct(x.tpr.interval.low)} – ${fmtPct(x.tpr.interval.high)}` : "—") },
            { key: "est", header: "Estimable", render: (x) => <Badge tone={x.estimable ? "ok" : "warn"}>{x.estimable ? "yes" : `needs ≥ ${x.min_negatives_required} negatives`}</Badge> },
          ]}
        />
      );
    case "exp5_watermark_length_entropy": {
      const p = pivot(res, "length", "zipf_exponent", "detection_rate");
      return <SimpleLines data={p.data} x="length" lines={p.lines} xLabel="tokens (zipf exponent: higher = lower entropy)" yLabel="detection rate" yDomain={[0, 1]} />;
    }
    case "exp6_watermark_robustness":
      return <SimpleLines data={res} x="replacement_fraction" lines={[{ key: "detection_rate", name: "detection rate" }]} xLabel="fraction of tokens replaced at random" yDomain={[0, 1]} />;
    case "exp7_threshold_selection":
      return (
        <SimpleTable
          rows={res.map((x: any, i: number) => ({ id: i, ...x }))}
          dense
          columns={[
            { key: "target_fpr", header: "Target FPR", render: (x) => fmtNum(x.target_fpr) },
            { key: "tokens", header: "Tokens" },
            { key: "z", header: "z threshold (normal)", render: (x) => fmtNum(x.z_threshold_normal, 2) },
            { key: "k", header: "Exact min. green count", render: (x) => x.exact_min_green_count ?? "unreachable" },
            { key: "a", header: "Exact achieved FPR", render: (x) => fmtNum(x.exact_achieved_fpr) },
            { key: "b", header: "True FPR of normal threshold", render: (x) => fmtNum(x.normal_threshold_true_fpr) },
          ]}
        />
      );
    case "exp8_strength_distortion":
      return <SimpleLines data={res} x="mean_kl_nats" lines={[{ key: "detection_rate", name: "detection rate" }]} xLabel="mean KL divergence from base model (nats)" yDomain={[0, 1]} />;
    case "exp9_fpr_calibration": {
      const p = pivot(res, "tokens", "z_threshold", "exact_fpr");
      const approx = pivot(res, "tokens", "z_threshold", "normal_approx_fpr");
      const merged = p.data.map((row, i) => ({ ...row, ...Object.fromEntries(Object.entries(approx.data[i]).filter(([k]) => k !== "tokens").map(([k, v]) => [`${k} approx`, v])) }));
      return <SimpleLines data={merged} x="tokens" logX logY lines={[...p.lines, ...approx.lines.map((l) => ({ key: `${l.key} approx`, dashed: true }))]} xLabel="scored tokens" yLabel="false-positive rate" />;
    }
    default:
      return <pre className="text-xs">{JSON.stringify(res, null, 2)}</pre>;
  }
}

function ExperimentCard({ e }: { e: (typeof EXPERIMENTS)[number] }) {
  const [cfg, setCfg] = React.useState<Record<string, number>>(e.defaults);
  const run = useMutation({ mutationFn: () => api<any>(`/evaluation/experiments/${e.id}/runs`, { json: { config: cfg } }) });
  React.useEffect(() => {
    if (["exp1_base_rate", "exp2_subgroup", "exp7_threshold_selection", "exp9_fpr_calibration"].includes(e.id)) run.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const r = run.data;
  return (
    <Panel
      title={e.title}
      subtitle={r ? r.question : "Run to compute"}
      actions={
        <>
          {r && <Badge tone={r.kind === "simulation" ? "warn" : "accent"}>{r.kind === "simulation" ? "Simulation" : "Analytical"}</Badge>}
          <Button size="sm" onClick={() => run.mutate()} loading={run.isPending} icon={<Play className="h-3.5 w-3.5" />}>Run</Button>
        </>
      }
    >
      {!!e.params.length && (
        <div className="mb-4 flex flex-wrap gap-3">
          {e.params.map((k) => (
            <label key={k} className="text-xs text-muted">
              <span className="mb-1 block font-mono">{k}</span>
              <Input type="number" step="any" value={cfg[k]} onChange={(ev) => setCfg({ ...cfg, [k]: Number(ev.target.value) })} className="h-8 w-28 py-1 text-xs" />
            </label>
          ))}
        </div>
      )}
      {run.error && <ErrorBlock error={run.error} />}
      {r && (
        <div className="space-y-4">
          <div className="text-[11px] font-medium uppercase tracking-wide text-warn/90">{r.label}</div>
          <ExperimentResult r={r} />
          <ul className="space-y-1 text-xs text-muted">
            {r.notes.map((n: string) => <li key={n}>• {n}</li>)}
          </ul>
          <div className="text-[11px] text-muted">Run {r.run_id} · config {JSON.stringify(r.config)}</div>
        </div>
      )}
    </Panel>
  );
}

export default function ResearchBenchPage() {
  return (
    <>
      <PageHeader
        eyebrow="Statistical reliability laboratory"
        title={<span className="flex items-center gap-3"><Microscope className="h-6 w-6 text-accent" /> Research bench</span>}
        description="When can an AI-content flag be trusted? Calculators and the nine analytical and simulation experiment categories. Simulations use synthetic generators and the AEGIS reference watermark; they are not real-world validation."
      />
      <PpvCalculator />
      <div className="mb-3 mt-8 flex items-center gap-2">
        <FlaskRound className="h-4 w-4 text-violet" />
        <h2 className="text-sm font-semibold">Experiment categories</h2>
        <span className="text-xs text-muted">Reproducible from <code className="hash">python -m aegis_research.experiments --all</code></span>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        {EXPERIMENTS.map((e) => <ExperimentCard key={e.id} e={e} />)}
      </div>
    </>
  );
}
