"use client";

import type { AnalysisProfile, EvidenceItem } from "@aegis/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Fingerprint, Play, ShieldCheck, ShieldX, UploadCloud } from "lucide-react";
import * as React from "react";

import { DemoBadge } from "@/components/badges";
import { Badge, Button, Callout, Dialog, Field, Hash, KV, Select, Textarea } from "@/components/ui";
import { ApiError, api, blobUrl, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, fmtBytes, fmtDate, humanize } from "@/lib/format";
import { ACCEPT, defaultProfile, uploadEvidence } from "@/lib/upload";

export function EvidenceThumb({ item }: { item: EvidenceItem }) {
  const [url, setUrl] = React.useState<string | null>(null);
  const has = item.versions.some((v) => v.kind === "thumbnail" && !v.purged_at);
  React.useEffect(() => {
    if (!has) return;
    let u: string | null = null;
    blobUrl(`/evidence/${item.id}/thumbnail`).then((x) => setUrl((u = x))).catch(() => undefined);
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [item.id, has]);
  if (!url) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={`Thumbnail of ${item.display_name}`} className="h-36 w-full rounded-lg border border-line/70 object-contain bg-black/40" />;
}

export function TextPreview({ item }: { item: EvidenceItem }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const hasRedacted = item.versions.some((v) => v.kind === "redacted");
  const [version, setVersion] = React.useState<"normalized" | "redacted">("normalized");
  const { data } = useQuery({ queryKey: ["text", item.id, version], queryFn: () => api<{ text: string; sha256: string }>(`/evidence/${item.id}/text?version=${version}`) });
  const ref = React.useRef<HTMLPreElement>(null);
  const [sel, setSel] = React.useState<[number, number] | null>(null);
  const [reason, setReason] = React.useState("");
  const redact = useMutation({
    mutationFn: () => api(`/evidence/${item.id}/redactions`, { json: { spans: [sel], reason } }),
    onSuccess: () => {
      setSel(null);
      setReason("");
      qc.invalidateQueries({ queryKey: ["evidence"] });
      setVersion("redacted");
    },
  });
  const onMouseUp = () => {
    const s = window.getSelection();
    if (!s || !ref.current || !s.rangeCount || s.isCollapsed) return;
    const r = s.getRangeAt(0);
    const pre = document.createRange();
    pre.selectNodeContents(ref.current);
    pre.setEnd(r.startContainer, r.startOffset);
    const start = pre.toString().length;
    setSel([start, start + r.toString().length]);
  };
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="label">Extracted text</span>
        {hasRedacted && (
          <Select className="h-7 w-40 py-0 text-xs" value={version} onChange={(e) => setVersion(e.target.value as any)} aria-label="Text version">
            <option value="normalized">Normalised</option>
            <option value="redacted">Latest redacted</option>
          </Select>
        )}
        {data && <Hash value={data.sha256} short className="ml-auto" />}
      </div>
      <pre ref={ref} onMouseUp={can("evidence.redact") ? onMouseUp : undefined} className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-line/70 bg-bg/60 p-3 font-mono text-[12px] leading-relaxed text-ink/85">
        {data?.text ?? "Loading…"}
      </pre>
      <p className="mt-1.5 text-[11px] text-muted">Untrusted content, displayed as data only. {can("evidence.redact") && "Select text to create a redacted derivative version; the original is preserved."}</p>
      {sel && (
        <div className="mt-3 space-y-2 rounded-lg border border-warn/30 bg-warn/5 p-3">
          <div className="text-xs text-warn">Redact characters {sel[0]}–{sel[1]} in a new version</div>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for redaction (recorded in the audit trail)" className="min-h-[60px]" />
          {redact.error && <Callout tone="danger">{(redact.error as Error).message}</Callout>}
          <div className="flex gap-2">
            <Button size="sm" variant="primary" disabled={reason.length < 5} loading={redact.isPending} onClick={() => redact.mutate()}>Create redacted version</Button>
            <Button size="sm" variant="ghost" onClick={() => setSel(null)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function EvidenceCard({ item, caseId, locked, onRun }: { item: EvidenceItem; caseId: string; locked: boolean; onRun: (item: EvidenceItem) => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const verify = useMutation({
    mutationFn: () => api<{ intact: boolean; note: string; versions: any[] }>(`/evidence/${item.id}/verify`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["evidence", caseId] }),
  });
  const original = item.versions.find((v) => v.kind === "original")!;
  const ex = item.extraction;
  return (
    <article id={`evidence-${item.id}`} className={cx("rounded-xl border bg-surface/80 p-5", item.status === "integrity_alert" ? "border-danger/60" : "border-line")}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <FileText className="h-4 w-4 text-muted" />
            <h3 className="truncate text-sm font-semibold">{item.display_name}</h3>
            <Badge>{item.modality}</Badge>
            <Badge tone={item.role === "process_evidence" ? "ok" : "slate"}>{humanize(item.role)}</Badge>
            {item.status !== "active" && <Badge tone="danger" dot>{humanize(item.status)}</Badge>}
            <DemoBadge show={item.is_demo_fixture} />
          </div>
          <div className="mt-1 text-xs text-muted">
            {item.mime_type} · {fmtBytes(original.size_bytes)} · acquired {fmtDate(item.acquired_at)} by {item.uploaded_by.display_name}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {can("evidence.verify") && (
            <Button size="sm" onClick={() => verify.mutate()} loading={verify.isPending} icon={<ShieldCheck className="h-3.5 w-3.5" />}>Verify integrity</Button>
          )}
          {can("evidence.download") && !original.purged_at && (
            <Button size="sm" variant="ghost" onClick={() => download(`/evidence/${item.id}/versions/${original.id}/download`, item.display_name)} icon={<Download className="h-3.5 w-3.5" />}>Original</Button>
          )}
          {can("analysis.run") && !locked && item.status === "active" && item.role === "primary" && (
            <Button size="sm" variant="primary" onClick={() => onRun(item)} icon={<Play className="h-3.5 w-3.5" />}>Run analysis</Button>
          )}
        </div>
      </div>
      {item.status === "integrity_alert" && (
        <div className="mt-4">
          <Callout tone="danger" title="Integrity alert">The stored bytes no longer match the hash recorded at acquisition. This evidence must not be treated as unchanged; analysis is blocked.</Callout>
        </div>
      )}
      {verify.data && (
        <div className="mt-4">
          <Callout tone={verify.data.intact ? "ok" : "danger"} title={verify.data.intact ? "All stored versions match their recorded SHA-256" : "Hash mismatch detected"}>
            {verify.data.note}
          </Callout>
        </div>
      )}
      <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <div className="space-y-4">
          <EvidenceThumb item={item} />
          {ex && (
            <KV
              items={[
                ["Extraction", ex.method],
                ["Tokens", `${ex.token_count} (${ex.tokenizer})`],
                ["Language", ex.language?.code ? `${ex.language.code} (${Math.round((ex.language.confidence ?? 0) * 100)}%)` : "not identified"],
                ["Sufficient for detectors", ex.sufficient_for_detection ? "yes" : "no — below minimum length"],
                ["OCR-derived", ex.ocr_derived ? "yes" : "no"],
                ["Sentences / paragraphs", `${ex.sentence_count} / ${ex.paragraph_count}`],
              ]}
            />
          )}
          {!!ex?.warnings?.length && <div className="space-y-1.5">{ex.warnings.map((w) => <Callout key={w} tone="warn">{w}</Callout>)}</div>}
        </div>
        <div>
          <div className="label mb-2 flex items-center gap-1.5"><Fingerprint className="h-3.5 w-3.5" /> Versions & chain of custody</div>
          <ol className="space-y-2">
            {item.versions.map((v) => (
              <li key={v.id} className="rounded-lg border border-line/70 bg-bg/40 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-mono text-muted">v{v.version_no}</span>
                  <Badge tone={v.kind === "original" ? "accent" : "slate"}>{humanize(v.kind)}</Badge>
                  <span className="text-muted">{fmtBytes(v.size_bytes)}</span>
                  {v.kind === "original" && <Badge tone={v.scan_status === "clean" ? "ok" : "slate"}>scan: {humanize(v.scan_status)}</Badge>}
                  {v.purged_at && <Badge tone="danger">purged {fmtDate(v.purged_at, false)}</Badge>}
                  <span className="ml-auto text-muted">{fmtDate(v.created_at)}</span>
                </div>
                <div className="mt-1.5"><Hash value={v.sha256} /></div>
                {!!v.transformations?.length && <div className="mt-1 text-[11px] text-muted">Transformations: {v.transformations.join(" → ")}</div>}
                {v.reason && <div className="mt-1 text-[11px] text-muted">Reason: {v.reason}</div>}
                {v.kind === "original" && Object.keys(v.metadata_status || {}).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {Object.entries(v.metadata_status).filter(([k]) => ["exif", "xmp", "icc_profile", "document_info", "core_properties", "container_tags"].includes(k)).map(([k, val]) => (
                      <Badge key={k} tone={val === "present" ? "accent" : val === "malformed" ? "danger" : "slate"}>{humanize(k)}: {String(val)}</Badge>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      </div>
      {(item.modality === "text" || item.modality === "document") && item.versions.some((v) => v.kind === "normalized_text" && !v.purged_at) && (
        <div className="mt-5"><TextPreview item={item} /></div>
      )}
    </article>
  );
}

export function UploadDialog({ caseId, open, onClose }: { caseId: string; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = React.useState<File | null>(null);
  const [role, setRole] = React.useState<"primary" | "process_evidence">("primary");
  const [desc, setDesc] = React.useState("");
  const [progress, setProgress] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await uploadEvidence(caseId, file, role, (s, t) => setProgress(s / t), desc || undefined);
      qc.invalidateQueries({ queryKey: ["evidence", caseId] });
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      setFile(null);
      setDesc("");
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="Add evidence" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} loading={busy} disabled={!file} icon={<UploadCloud className="h-4 w-4" />}>Acquire</Button></>}>
      <Field label="File" hint="Validated by content, hashed with SHA-256 and stored write-once.">
        <input type="file" accept={ACCEPT} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="input file:mr-3 file:rounded file:border-0 file:bg-raised file:px-3 file:py-1 file:text-ink" />
      </Field>
      <Field label="Role">
        <Select value={role} onChange={(e) => setRole(e.target.value as any)}>
          <option value="primary">Primary evidence</option>
          <option value="process_evidence">Process evidence (drafts, revision history, notes)</option>
        </Select>
      </Field>
      <Field label="Description"><Textarea value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
      {role === "process_evidence" && <Callout tone="slate">Process evidence is recorded as a separate evidence category for reviewers. It is not automatically treated as proof of authorship.</Callout>}
      {busy && progress > 0 && <div className="h-1 rounded bg-raised"><div className="h-1 rounded bg-accent" style={{ width: `${progress * 100}%` }} /></div>}
      {error && <Callout tone="danger">{error}</Callout>}
    </Dialog>
  );
}

export function RunDialog({ caseId, item, onClose, onQueued }: { caseId: string; item: EvidenceItem | null; onClose: () => void; onQueued: (jobId: string) => void }) {
  const { data: profiles } = useQuery({ queryKey: ["profiles"], queryFn: () => api<AnalysisProfile[]>("/analysis/profiles") });
  const [profile, setProfile] = React.useState("");
  const [fps, setFps] = React.useState("2");
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (item) setProfile(defaultProfile(item.modality));
  }, [item]);
  if (!item) return null;
  const applicable = profiles?.filter((p) => p.modalities.includes(item.modality)) ?? [];
  const chosen = applicable.find((p) => p.id === profile);
  const mods = (m: { modalities: string[] }) => m.modalities.includes(item.modality) || (item.modality === "document" && m.modalities.includes("text"));
  const submit = async () => {
    setError(null);
    try {
      const job = await api<{ id: string }>(`/analysis/investigations/${caseId}/jobs`, {
        json: { evidence_item_id: item.id, profile_id: profile, options: item.modality === "video" ? { sample_fps: Number(fps) } : {} },
      });
      onQueued(job.id);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <Dialog open onClose={onClose} title={`Analyse ${item.display_name}`} wide footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} icon={<Play className="h-4 w-4" />}>Queue analysis</Button></>}>
      <Field label="Analysis profile">
        <Select value={profile} onChange={(e) => setProfile(e.target.value)}>
          {applicable.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </Field>
      {item.modality === "video" && (
        <Field label="Frame sampling rate (fps)" hint="Between 0.1 and 10. Higher rates take longer.">
          <Select value={fps} onChange={(e) => setFps(e.target.value)}>{["0.5", "1", "2", "4"].map((f) => <option key={f}>{f}</option>)}</Select>
        </Field>
      )}
      {chosen && (
        <div>
          <p className="text-sm text-muted">{chosen.description} · {chosen.resources}</p>
          <ul className="mt-3 divide-y divide-line/50 rounded-lg border border-line/70">
            {chosen.methods.filter(mods).map((m) => (
              <li key={m.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                {m.available ? <ShieldCheck className="h-4 w-4 text-ok" /> : <ShieldX className="h-4 w-4 text-muted" />}
                <span className={m.available ? "" : "text-muted"}>{m.name}</span>
                {m.external_processing && <Badge tone="warn">external</Badge>}
                <span className="ml-auto max-w-[45%] truncate text-xs text-muted" title={m.reason}>{m.available ? humanize(m.evidence_class) : m.reason}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">Unavailable methods are recorded as unavailable in the results — never as negative findings.</p>
        </div>
      )}
      {error && <Callout tone="danger">{error}</Callout>}
    </Dialog>
  );
}
