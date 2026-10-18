"use client";

import type { AnalysisJob, Artifact, DetectorRun, EvidenceClass, Fusion } from "@aegis/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  ChevronDown,
  CircleSlash,
  Fingerprint,
  GitCompareArrows,
  Lightbulb,
  ListChecks,
  ShieldAlert,
  Sigma,
  Waves,
} from "lucide-react";
import * as React from "react";

import { EvidenceClassBadge, JobStatusBadge, OutcomeBadge, RunStatusBadge } from "@/components/badges";
import { Sparkline } from "@/components/charts";
import { Badge, Callout, Hash, KV, Panel, Progress, Skeleton } from "@/components/ui";
import { api, blobUrl, streamEvents } from "@/lib/api";
import { EVIDENCE_CLASS, cx, fmtDate, fmtNum, humanize } from "@/lib/format";

const TERMINAL = new Set(["completed", "completed_with_failures", "failed", "cancelled"]);

/** Job state from the API, refreshed whenever the server-sent event stream reports a persisted change. */
export function useJob(jobId: string | null | undefined) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["job", jobId], queryFn: () => api<AnalysisJob>(`/analysis/jobs/${jobId}`), enabled: !!jobId });
  const status = q.data?.status;
  React.useEffect(() => {
    if (!jobId || !status || TERMINAL.has(status)) return;
    const ctl = new AbortController();
    streamEvents(`/analysis/jobs/${jobId}/events`, () => qc.invalidateQueries({ queryKey: ["job", jobId] }), ctl.signal).catch(() => undefined);
    return () => ctl.abort();
  }, [jobId, status, qc]);
  React.useEffect(() => {
    if (status && TERMINAL.has(status)) {
      qc.invalidateQueries({ queryKey: ["case"] });
      qc.invalidateQueries({ queryKey: ["evidence"] });
    }
  }, [status, qc]);
  return q;
}

export function JobHeader({ job }: { job: AnalysisJob }) {
  const active = !TERMINAL.has(job.status);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <JobStatusBadge value={job.status} />
        <span className="text-sm text-muted">Profile</span>
        <span className="text-sm font-medium">{humanize(job.profile_id)}</span>
        <span className="text-xs text-muted">· queued {fmtDate(job.created_at)}</span>
        {job.finished_at && <span className="text-xs text-muted">· finished {fmtDate(job.finished_at)}</span>}
        {!job.external_processing_permitted && (
          <Badge tone="ok" title="No evidence was sent to external services for this job">
            Local processing only
          </Badge>
        )}
      </div>
      <Progress done={job.methods_done} total={job.methods_total} active={active} />
      {active && (
        <p className="text-xs text-muted">
          States shown are the persisted state of each method. Methods that do not report progress are shown as “Running” until they finish.
        </p>
      )}
      {job.error && <Callout tone="danger" title="Job error">{job.error}</Callout>}
    </div>
  );
}

export function FusionPanel({ fusion }: { fusion: Fusion }) {
  return (
    <Panel
      title="Automated evidence assessment"
      subtitle={`Policy ${fusion.policy} · signals are sorted by evidence class, never averaged`}
      icon={<GitCompareArrows className="h-4 w-4" />}
    >
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeBadge value={fusion.primary_outcome} label={fusion.primary_label} />
        {fusion.categories
          .filter((c) => c !== fusion.primary_outcome)
          .map((c) => (
            <OutcomeBadge key={c} value={c} />
          ))}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink/90">{fusion.statement}</p>
      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <FusionList icon={<ListChecks className="h-4 w-4 text-violet" />} title="Signals consistent with AI generation" items={fusion.agreeing} empty="None" />
        <FusionList icon={<AlertOctagon className="h-4 w-4 text-warn" />} title="Conflicting signals" items={fusion.conflicting} empty="No contradictions identified" />
        <FusionList icon={<CircleSlash className="h-4 w-4 text-muted" />} title="Unavailable or blocked methods" items={fusion.missing.map((m) => `${m.method_id} — ${m.reason}`)} empty="All profile methods ran" />
        <FusionList icon={<ShieldAlert className="h-4 w-4 text-danger" />} title="Failed methods (not negative results)" items={fusion.failed.map((m) => `${m.method_id} — ${m.reason}`)} empty="None" />
      </div>
      {!!fusion.uncertainty_reasons.length && (
        <div className="mt-5">
          <div className="label mb-2">Why the result remains uncertain</div>
          <ul className="space-y-1.5 text-sm text-ink/85">
            {fusion.uncertainty_reasons.map((r) => (
              <li key={r} className="flex gap-2">
                <Sigma className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" /> {r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!fusion.suggested_next_steps.length && (
        <div className="mt-5 rounded-lg border border-line/70 bg-bg/40 p-4">
          <div className="label mb-2 flex items-center gap-1.5">
            <Lightbulb className="h-3.5 w-3.5" /> Evidence that could help
          </div>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink/85">
            {fusion.suggested_next_steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-4 text-xs text-muted">Calibration applies to at least one signal: {fusion.calibration_applies ? "yes" : "no"}.</p>
    </Panel>
  );
}

function FusionList({ title, items, empty, icon }: { title: string; items: string[]; empty: string; icon: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-ink/90">
        {icon} {title}
      </div>
      {items.length ? (
        <ul className="space-y-1">
          {items.map((i) => (
            <li key={i} className="break-words rounded-md bg-raised/50 px-2.5 py-1.5 font-mono text-[11.5px] text-ink/85">
              {i}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted">{empty}</p>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------------------- artifacts */

export function ArtifactImage({ artifact }: { artifact: Artifact }) {
  const [url, setUrl] = React.useState<string | null>(null);
  React.useEffect(() => {
    let u: string | null = null;
    blobUrl(`/artifacts/${artifact.id}`)
      .then((x) => setUrl((u = x)))
      .catch(() => setUrl(null));
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [artifact.id]);
  return (
    <figure className="overflow-hidden rounded-lg border border-line/80 bg-bg/60">
      <div className="flex min-h-40 items-center justify-center bg-black/40">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={artifact.description} className="max-h-80 w-full object-contain [image-rendering:pixelated]" />
        ) : (
          <Skeleton className="h-40 w-full rounded-none" />
        )}
      </div>
      <figcaption className="space-y-1 p-3 text-xs">
        <div className="font-medium text-ink">{humanize(artifact.name.replace(/\.png$/, ""))}</div>
        <div className="text-muted">{artifact.description}</div>
        <div className="flex gap-1.5 text-warn/90">
          <span className="font-medium">Cannot establish:</span> <span>{artifact.cannot_establish}</span>
        </div>
      </figcaption>
    </figure>
  );
}

/* ----------------------------------------------------------------------------- method outputs */

function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-line/70 bg-bg/40 px-3 py-2.5" title={hint}>
      <div className="label">{label}</div>
      <div className="mt-1 font-mono text-sm tabular-nums text-ink">{value ?? "—"}</div>
    </div>
  );
}

function WatermarkView({ o }: { o: Record<string, any> }) {
  const z = o.z_score as number | null;
  const thr = o.z_threshold as number;
  const pct = z == null ? 0 : Math.max(0, Math.min(1, (z + 2) / (Math.max(thr * 2, z) + 2)));
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 flex justify-between text-xs text-muted">
          <span>z-score under H₀ (not watermarked with this key)</span>
          <span>threshold z ≥ {thr}</span>
        </div>
        <div className="relative h-2.5 rounded-full bg-raised">
          <div className={cx("h-full rounded-full", o.detected ? "bg-cyan" : "bg-slate-500")} style={{ width: `${pct * 100}%` }} />
          <div className="absolute inset-y-[-3px] w-px bg-warn" style={{ left: `${((thr + 2) / (Math.max(thr * 2, z ?? 0) + 2)) * 100}%` }} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Metric label="z-score" value={fmtNum(z, 2)} />
        <Metric label="Green / scored" value={`${o.green_tokens} / ${o.scored_tokens}`} />
        <Metric label="Exact p-value" value={fmtNum(o.p_value_exact)} hint="Binomial tail probability" />
        <Metric label="Normal approx. p" value={fmtNum(o.p_value_normal_approx)} />
      </div>
      <p className="text-xs text-muted">
        Key fingerprint <code className="hash">{o.key_fingerprint}</code> · γ = {o.gamma} · vocabulary {o.vocabulary}. The key itself never leaves the server.
      </p>
    </div>
  );
}

function ProvenanceView({ o }: { o: Record<string, any> }) {
  const state = o.state as string;
  const tone = { signature_valid_signer_trusted: "ok", signature_valid_signer_untrusted: "accent", verification_failed: "danger", no_manifest: "slate", unsupported_format: "slate" }[state] ?? "slate";
  return (
    <div className="space-y-4">
      <div className="grid gap-2 md:grid-cols-3">
        <Check label="Manifest present" ok={state !== "no_manifest" && state !== "unsupported_format"} />
        <Check label="Signature & hashes validate" ok={state === "signature_valid_signer_trusted" || state === "signature_valid_signer_untrusted"} fail={state === "verification_failed"} />
        <Check label="Signer chains to trust anchor" ok={state === "signature_valid_signer_trusted"} />
      </div>
      <Badge tone={tone}>{humanize(state)}</Badge>
      {state !== "no_manifest" && state !== "unsupported_format" && (
        <>
          <KV
            cols={3}
            items={[
              ["Signer (certificate)", o.signature ? `${o.signature.common_name ?? "—"} · ${o.signature.issuer ?? "—"}` : "—"],
              ["Algorithm", o.signature?.algorithm],
              ["Claim generator", (o.claim_generator || []).map((g: any) => `${g.name} ${g.version ?? ""}`).join(", ") || "—"],
              ["Declared source types", (o.digital_source_types || []).join(", ") || "—"],
              ["Ingredients", String(o.ingredients?.length ?? 0)],
              ["Embedded", o.embedded == null ? "—" : o.embedded ? "yes" : "no (remote)"],
            ]}
          />
          {!!o.actions?.length && (
            <div>
              <div className="label mb-1.5">Declared editing actions</div>
              <div className="flex flex-wrap gap-1.5">
                {o.actions.map((a: any, i: number) => (
                  <Badge key={i}>
                    {a.action}
                    {a.digital_source_type ? ` · ${a.digital_source_type}` : ""}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {!!o.failure_codes?.length && (
            <div>
              <div className="label mb-1.5">Validation failures</div>
              <div className="flex flex-wrap gap-1.5">
                {o.failure_codes.map((c: string) => (
                  <Badge key={c} tone={c === "signingCredential.untrusted" ? "warn" : "danger"}>
                    {c}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      <Callout tone="slate">
        A valid signature shows the record is intact and was signed by the holder of the certificate. It does not establish that the
        manifest&apos;s claims are true. “No supported provenance record found” is not evidence of AI generation or human creation.
      </Callout>
    </div>
  );
}

function Check({ label, ok, fail }: { label: string; ok: boolean; fail?: boolean }) {
  return (
    <div className={cx("flex items-center gap-2 rounded-lg border px-3 py-2 text-sm", ok ? "border-ok/30 bg-ok/5" : fail ? "border-danger/30 bg-danger/5" : "border-line/70 bg-bg/40")}>
      <span className={cx("h-2 w-2 rounded-full", ok ? "bg-ok" : fail ? "bg-danger" : "bg-slate-500")} />
      <span className={ok ? "text-ink" : "text-muted"}>{label}</span>
    </div>
  );
}

function StatsGrid({ o, keys }: { o: Record<string, any>; keys: [string, string][] }) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {keys.map(([k, label]) => (
        <Metric key={k} label={label} value={typeof o[k] === "number" ? fmtNum(o[k]) : o[k] == null ? "—" : String(o[k])} />
      ))}
    </div>
  );
}

function RecordTable({ data }: { data: Record<string, any> }) {
  const entries = Object.entries(data || {});
  if (!entries.length) return <p className="text-xs text-muted">None present.</p>;
  return (
    <div className="max-h-64 overflow-auto rounded-lg border border-line/70">
      <table className="w-full text-xs">
        <tbody className="divide-y divide-line/50">
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td className="w-1/3 px-3 py-1.5 font-mono text-muted">{k}</td>
              <td className="break-all px-3 py-1.5 text-ink/90">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SegmentTimeline({ segments, duration }: { segments: { start: number; end: number; label: string }[]; duration: number }) {
  const colors: Record<string, string> = { duplicate_or_frozen_frame: "bg-warn", abrupt_discontinuity: "bg-danger", noise_level_shift: "bg-violet", active_signal: "bg-cyan" };
  return (
    <div>
      <div className="relative h-7 overflow-hidden rounded-md border border-line/70 bg-bg/60">
        {segments.map((s, i) => (
          <div
            key={i}
            title={`${humanize(s.label)} ${s.start.toFixed(1)}–${s.end.toFixed(1)} s`}
            className={cx("absolute inset-y-1 min-w-[2px] rounded-sm opacity-80", colors[s.label] ?? "bg-accent")}
            style={{ left: `${(s.start / duration) * 100}%`, width: `${((s.end - s.start) / duration) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-3 text-[11px] text-muted">
        {Array.from(new Set(segments.map((s) => s.label))).map((l) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className={cx("h-2 w-2 rounded-sm", colors[l] ?? "bg-accent")} /> {humanize(l)} ({segments.filter((s) => s.label === l).length})
          </span>
        ))}
        <span className="ml-auto">0 – {duration.toFixed(1)} s</span>
      </div>
    </div>
  );
}

function SegmentsLoader({ runId, duration }: { runId: string; duration: number }) {
  const { data } = useQuery({ queryKey: ["segments", runId], queryFn: () => api<any[]>(`/analysis/runs/${runId}/segments`) });
  if (!data) return <Skeleton className="h-7 w-full" />;
  if (!data.length) return <p className="text-xs text-muted">No timeline observations.</p>;
  return <SegmentTimeline segments={data} duration={duration} />;
}

function MethodOutput({ run }: { run: DetectorRun }) {
  const o = run.output || {};
  switch (run.method_id) {
    case "watermark.aegis_reference_text":
      return o.z_score != null ? <WatermarkView o={o} /> : null;
    case "provenance.c2pa":
      return <ProvenanceView o={o} />;
    case "text.descriptive_statistics":
      return (
        <StatsGrid
          o={o}
          keys={[
            ["words", "Words"],
            ["sentences", "Sentences"],
            ["type_token_ratio", "Type-token ratio"],
            ["mattr_50", "MATTR (50)"],
            ["mean_sentence_words", "Mean sentence length"],
            ["sentence_length_cv", "Sentence-length CV"],
            ["zlib_compression_ratio", "Compression ratio"],
            ["unigram_entropy_bits", "Unigram entropy (bits)"],
          ]}
        />
      );
    case "image.metadata":
      return (
        <div className="space-y-3">
          <StatsGrid
            o={{ ...o, dims: `${o.width}×${o.height}`, quality: o.jpeg?.estimated_quality }}
            keys={[
              ["format", "Format"],
              ["dims", "Dimensions"],
              ["mode", "Colour mode"],
              ["exif_status", "EXIF"],
              ["icc_profile", "ICC profile"],
              ["quality", "Est. JPEG quality"],
              ["orientation", "Orientation"],
              ["xmp_present", "XMP present"],
            ]}
          />
          <details className="group">
            <summary className="cursor-pointer text-xs text-accent">EXIF fields ({Object.keys(o.exif || {}).length})</summary>
            <div className="mt-2">
              <RecordTable data={o.exif} />
            </div>
          </details>
        </div>
      );
    case "metadata.declared_generation_claims":
      return o.declarations?.length ? (
        <div className="space-y-2">
          {o.generator_markers?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {o.generator_markers.map((m: string) => (
                <Badge key={m} tone="warn">
                  declares: {m}
                </Badge>
              ))}
            </div>
          )}
          <RecordTable data={Object.fromEntries(o.declarations.map((d: any) => [d.field, d.value]))} />
        </div>
      ) : null;
    case "audio.signal_analysis":
      return (
        <StatsGrid
          o={{ ...o, bw: o.effective_bandwidth_99_hz ? `${Math.round(o.effective_bandwidth_99_hz)} Hz` : null }}
          keys={[
            ["codec", "Codec"],
            ["native_sample_rate", "Sample rate"],
            ["channels", "Channels"],
            ["duration_seconds", "Duration (s)"],
            ["peak_dbfs", "Peak dBFS"],
            ["rms_dbfs", "RMS dBFS"],
            ["clipping_fraction", "Clipping"],
            ["bw", "99% bandwidth"],
          ]}
        />
      );
    case "video.container":
      return (
        <div className="space-y-3">
          <div className="overflow-x-auto rounded-lg border border-line/70">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line/70 text-left">
                  {["#", "Type", "Codec", "Resolution", "FPS", "Start", "Duration"].map((h) => (
                    <th key={h} className="label px-3 py-1.5">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50">
                {(o.streams || []).map((s: any) => (
                  <tr key={s.index}>
                    <td className="px-3 py-1.5">{s.index}</td>
                    <td className="px-3 py-1.5">{s.type}</td>
                    <td className="px-3 py-1.5 font-mono">{s.codec}</td>
                    <td className="px-3 py-1.5">{s.width ? `${s.width}×${s.height}` : "—"}</td>
                    <td className="px-3 py-1.5">{fmtNum(s.avg_frame_rate, 2)}</td>
                    <td className="px-3 py-1.5">{fmtNum(s.start_time)}</td>
                    <td className="px-3 py-1.5">{fmtNum(s.duration)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {o.av_alignment && (
            <KV
              items={[
                ["A/V start offset (s)", fmtNum(o.av_alignment.start_offset_seconds)],
                ["A/V duration difference (s)", fmtNum(o.av_alignment.duration_difference_seconds)],
              ]}
            />
          )}
          {o.structural_findings?.map((f: string) => (
            <Callout key={f} tone="warn">
              {f}
            </Callout>
          ))}
        </div>
      );
    case "video.temporal_consistency":
      return (
        <div className="space-y-4">
          <StatsGrid
            o={o}
            keys={[
              ["sampled_frames", "Sampled frames"],
              ["sample_fps", "Sample rate (fps)"],
              ["keyframe_count", "Keyframes"],
              ["mean_interframe_change", "Mean inter-frame change"],
            ]}
          />
          <div>
            <div className="label mb-1 flex items-center gap-1.5">
              <Waves className="h-3.5 w-3.5" /> Inter-frame change
            </div>
            <Sparkline data={o.interframe_change_series || []} />
          </div>
          <div>
            <div className="label mb-1.5">Timeline of observations</div>
            <SegmentsLoader runId={run.id} duration={(o.sampled_frames || 1) / (o.sample_fps || 1)} />
          </div>
        </div>
      );
    default:
      if (["image.noise_residual", "image.frequency_spectrum", "image.error_level_analysis"].includes(run.method_id))
        return <StatsGrid o={o} keys={Object.keys(o).filter((k) => typeof o[k] !== "object").slice(0, 8).map((k) => [k, humanize(k)])} />;
      return Object.keys(o).length ? (
        <details>
          <summary className="cursor-pointer text-xs text-accent">Raw output</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-bg/70 p-3 font-mono text-[11px] text-ink/80">{JSON.stringify(o, null, 2)}</pre>
        </details>
      ) : null;
  }
}

export function RunCard({ run }: { run: DetectorRun }) {
  const [open, setOpen] = React.useState(run.status === "completed");
  React.useEffect(() => {
    if (run.status === "completed" || run.status === "failed") setOpen(true);
  }, [run.status]);
  const muted = ["unavailable", "unsupported_input", "cancelled", "pending"].includes(run.status);
  return (
    <article className={cx("rounded-xl border bg-surface/80 transition-colors", muted ? "border-line/50" : "border-line", run.flagged && "border-violet/40")}>
      <button className="flex w-full items-start gap-3 p-4 text-left" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cx("text-sm font-medium", muted ? "text-muted" : "text-ink")}>{run.method_name}</span>
            <span className="font-mono text-[11px] text-muted">v{run.method_version}</span>
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">{run.summary ?? "Waiting for worker."}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <RunStatusBadge value={run.status} />
          <EvidenceClassBadge value={run.evidence_class} />
        </div>
        <ChevronDown className={cx("mt-1 h-4 w-4 shrink-0 text-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-4 border-t border-line/60 p-4">
          {run.score != null && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg bg-bg/50 px-3 py-2.5 text-sm">
              <span className="label">Output</span>
              <span className="font-mono tabular-nums">{fmtNum(run.score, 4)}</span>
              <span className="text-xs text-muted">{run.score_semantics}</span>
              <span className="ml-auto flex gap-1.5">
                <Badge tone={run.calibrated ? "ok" : "slate"}>{run.calibrated ? "Calibrated" : "Uncalibrated — not a probability"}</Badge>
                {run.flagged != null && <Badge tone={run.flagged ? "violet" : "slate"}>{run.flagged ? "Above validated threshold" : "Below threshold"}</Badge>}
              </span>
            </div>
          )}
          <MethodOutput run={run} />
          {!!run.artifacts?.length && (
            <div className="grid gap-3 md:grid-cols-2">
              {run.artifacts.map((a) => (
                <ArtifactImage key={a.id} artifact={a} />
              ))}
            </div>
          )}
          {!!run.warnings?.length && (
            <div className="space-y-1.5">
              {run.warnings.map((w) => (
                <Callout key={w} tone="warn">
                  {w}
                </Callout>
              ))}
            </div>
          )}
          {run.error && (
            <pre className="overflow-auto rounded-lg border border-danger/30 bg-danger/5 p-3 font-mono text-[11px] text-danger">{run.error}</pre>
          )}
          <details>
            <summary className="cursor-pointer text-xs text-muted hover:text-ink">Known limitations ({run.limitations.length})</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted">
              {run.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
            <span className="flex items-center gap-1">
              <Fingerprint className="h-3 w-3" /> input <Hash value={run.input_sha256} short />
            </span>
            {run.duration_ms != null && <span>{run.duration_ms} ms</span>}
            <span>schema {run.output_schema}</span>
            {Object.keys(run.config || {}).length > 0 && <span>config {JSON.stringify(run.config)}</span>}
          </div>
        </div>
      )}
    </article>
  );
}

const CLASS_ORDER: EvidenceClass[] = [
  "cryptographic_provenance",
  "verified_watermark",
  "statistical_inference",
  "media_forensic_observation",
  "declared_metadata",
  "process_evidence",
];

/** Runs grouped by evidence class: different forms of evidence are never mixed in one list. */
export function RunsByClass({ runs }: { runs: DetectorRun[] }) {
  return (
    <div className="space-y-6">
      {CLASS_ORDER.map((cls) => {
        const rs = runs.filter((r) => r.evidence_class === cls);
        if (!rs.length) return null;
        return (
          <section key={cls}>
            <div className="mb-2.5 flex items-baseline gap-3">
              <h3 className="text-sm font-semibold">{EVIDENCE_CLASS[cls].label}</h3>
              <span className="text-xs text-muted">{EVIDENCE_CLASS[cls].description}</span>
            </div>
            <div className="space-y-2.5">
              {rs.map((r) => (
                <RunCard key={r.id} run={r} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function JobView({ jobId }: { jobId: string }) {
  const { data: job, isLoading } = useJob(jobId);
  if (isLoading || !job) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-5">
      <JobHeader job={job} />
      {job.fusion && <FusionPanel fusion={job.fusion} />}
      <RunsByClass runs={job.runs} />
    </div>
  );
}
