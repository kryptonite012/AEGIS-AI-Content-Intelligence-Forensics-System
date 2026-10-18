"use client";

import type { AnalysisProfile, EvidenceItem, Investigation } from "@aegis/shared-types";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, FileUp, Fingerprint, Play, ShieldAlert, Trash2, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { EvidenceClassBadge, ImplementationBadge } from "@/components/badges";
import { Badge, Button, Callout, Field, Hash, Input, PageHeader, Panel, Select, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cx, fmtBytes } from "@/lib/format";
import { ACCEPT, defaultProfile, sha256Hex, uploadEvidence } from "@/lib/upload";

const schema = z.object({
  title: z.string().min(3, "At least 3 characters").max(300),
  case_reference: z.string().min(2).max(80).regex(/^[A-Za-z0-9._/-]+$/, "Letters, digits and . _ / - only"),
  purpose: z.string().min(10, "Describe the purpose (at least 10 characters)").max(4000),
  media_category: z.enum(["text", "document", "image", "audio", "video", "mixed"]),
  description: z.string().max(20000).optional(),
  priority: z.enum(["low", "normal", "high", "urgent"]),
  assigned_reviewer_id: z.string().optional(),
  legal_basis: z.string().max(4000).optional(),
  retention_class: z.enum(["standard", "extended", "legal_minimum", "research"]),
  access_classification: z.enum(["standard", "restricted"]),
});
type FormValues = z.infer<typeof schema>;

type Pending = { file: File; role: "primary" | "process_evidence"; clientHash?: string | null; progress: number; item?: EvidenceItem; error?: string; profile?: string };

const STEPS = ["Case details", "Evidence", "Analysis profile"];

export default function NewInvestigationPage() {
  const router = useRouter();
  const [step, setStep] = React.useState(0);
  const [inv, setInv] = React.useState<Investigation | null>(null);
  const [files, setFiles] = React.useState<Pending[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      priority: "normal",
      media_category: "text",
      retention_class: "standard",
      access_classification: "standard",
      case_reference: `CASE-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`,
    },
  });
  const reviewers = useQuery({
    queryKey: ["reviewer-candidates"],
    queryFn: () => api<{ id: string; display_name: string; role: string }[]>("/reviewers"),
  });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<AnalysisProfile[]>("/analysis/profiles") });

  const createCase = form.handleSubmit(async (v) => {
    setErr(null);
    try {
      const body = { ...v, assigned_reviewer_id: v.assigned_reviewer_id || undefined, legal_basis: v.legal_basis || undefined };
      setInv(await api<Investigation>("/investigations", { json: body }));
      setStep(1);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  });

  const addFiles = async (list: FileList | null) => {
    if (!list) return;
    const next = Array.from(list).map((f) => ({ file: f, role: "primary" as const, progress: 0 }));
    setFiles((cur) => [...cur, ...next]);
    for (const p of next) {
      const h = await sha256Hex(p.file);
      setFiles((cur) => cur.map((x) => (x.file === p.file ? { ...x, clientHash: h } : x)));
    }
  };

  const uploadAll = async () => {
    if (!inv) return;
    setBusy(true);
    for (const p of files) {
      if (p.item) continue;
      try {
        const item = await uploadEvidence(inv.id, p.file, p.role, (s, t) =>
          setFiles((cur) => cur.map((x) => (x.file === p.file ? { ...x, progress: s / t } : x))),
        );
        setFiles((cur) => cur.map((x) => (x.file === p.file ? { ...x, item, error: undefined, profile: defaultProfile(item.modality) } : x)));
      } catch (e) {
        setFiles((cur) => cur.map((x) => (x.file === p.file ? { ...x, error: e instanceof ApiError ? e.message : String(e) } : x)));
      }
    }
    setBusy(false);
  };

  const runAnalyses = async () => {
    if (!inv) return;
    setBusy(true);
    try {
      for (const p of files) {
        if (!p.item || !p.profile || p.item.role === "process_evidence") continue;
        await api(`/analysis/investigations/${inv.id}/jobs`, {
          json: { evidence_item_id: p.item.id, profile_id: p.profile },
          headers: { "Idempotency-Key": `${p.item.id}:${p.profile}` },
        });
      }
      router.push(`/cases/${inv.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  const uploaded = files.filter((f) => f.item);
  return (
    <>
      <PageHeader eyebrow="Operations" title="New investigation" description="Open a case, acquire evidence into the write-once vault, then choose which methods to run. Only collect the information the investigation needs." />
      <ol className="mb-6 flex flex-wrap gap-2">
        {STEPS.map((s, i) => (
          <li key={s} className={cx("flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs", i === step ? "border-accent/50 bg-accent/10 text-ink" : i < step ? "border-ok/30 text-ok" : "border-line text-muted")}>
            {i < step ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="font-mono">{i + 1}</span>} {s}
          </li>
        ))}
      </ol>
      {err && <div className="mb-4"><Callout tone="danger">{err}</Callout></div>}

      {step === 0 && (
        <Panel title="Case details" subtitle="Recorded in the audit trail. Avoid unnecessary personal information.">
          <form onSubmit={createCase} className="grid gap-5 md:grid-cols-2" noValidate>
            <Field label="Case title" required error={form.formState.errors.title?.message}>
              <Input {...form.register("title")} placeholder="e.g. Authorship query — grant application section 3" />
            </Field>
            <Field label="Case reference" required error={form.formState.errors.case_reference?.message}>
              <Input className="font-mono" {...form.register("case_reference")} />
            </Field>
            <div className="md:col-span-2">
              <Field label="Purpose" required error={form.formState.errors.purpose?.message} hint="Why this examination is needed and what question it should answer.">
                <Textarea {...form.register("purpose")} />
              </Field>
            </div>
            <Field label="Media category">
              <Select {...form.register("media_category")}>
                {["text", "document", "image", "audio", "video", "mixed"].map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Priority">
              <Select {...form.register("priority")}>
                {["low", "normal", "high", "urgent"].map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Assigned independent reviewer" hint={reviewers.data?.length ? "Must be someone other than you." : "Reviewers can be assigned later from the case."}>
              <Select {...form.register("assigned_reviewer_id")}>
                <option value="">Assign later</option>
                {reviewers.data?.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
              </Select>
            </Field>
            <Field label="Access classification" hint="Restricted cases are visible only to you, the reviewer, auditors and administrators.">
              <Select {...form.register("access_classification")}>
                <option value="standard">Standard</option>
                <option value="restricted">Restricted</option>
              </Select>
            </Field>
            <Field label="Retention classification">
              <Select {...form.register("retention_class")}>
                <option value="standard">Standard</option>
                <option value="extended">Extended</option>
                <option value="legal_minimum">Legal minimum</option>
                <option value="research">Research</option>
              </Select>
            </Field>
            <Field label="Legal or organisational basis" hint="Where required by your institution.">
              <Input {...form.register("legal_basis")} placeholder="e.g. Academic integrity policy §4.2" />
            </Field>
            <div className="md:col-span-2">
              <Field label="Description">
                <Textarea {...form.register("description")} />
              </Field>
            </div>
            <div className="flex justify-end md:col-span-2">
              <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>Create case and continue</Button>
            </div>
          </form>
        </Panel>
      )}

      {step === 1 && inv && (
        <Panel title="Acquire evidence" subtitle={`${inv.case_reference} · files are validated by content, hashed with SHA-256 and stored write-once`}>
          <label
            className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-line bg-bg/40 px-6 py-10 text-center transition-colors hover:border-accent/50 hover:bg-accent/[0.03]"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              addFiles(e.dataTransfer.files);
            }}
          >
            <UploadCloud className="h-8 w-8 text-accent" />
            <span className="mt-3 text-sm font-medium">Drop files or click to select</span>
            <span className="mt-1 text-xs text-muted">TXT, PDF, DOCX, PNG, JPEG, WebP, WAV, MP3, M4A, MP4 · executables, macros and unsafe archives are rejected</span>
            <input type="file" multiple accept={ACCEPT} className="sr-only" onChange={(e) => addFiles(e.target.files)} />
          </label>
          {!!files.length && (
            <ul className="mt-5 divide-y divide-line/60 rounded-xl border border-line/70">
              {files.map((p) => (
                <li key={p.file.name + p.file.size} className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
                  <FileUp className="h-5 w-5 shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">{p.file.name}</span>
                      <span className="text-xs text-muted">{fmtBytes(p.file.size)}</span>
                      {p.item && <Badge tone="ok" dot>Acquired · {p.item.modality}</Badge>}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
                      <Fingerprint className="h-3 w-3" />
                      {p.item ? (
                        <>server SHA-256 <Hash value={p.item.versions[0].sha256} short />{p.clientHash && (p.clientHash === p.item.versions[0].sha256 ? <Badge tone="ok">matches local hash</Badge> : <Badge tone="danger">differs from local hash</Badge>)}</>
                      ) : p.clientHash ? (
                        <>local SHA-256 <Hash value={p.clientHash} short /></>
                      ) : (
                        "computing local hash…"
                      )}
                    </div>
                    {p.error && <p className="mt-1.5 text-xs text-danger">{p.error}</p>}
                    {!p.item && p.progress > 0 && p.progress < 1 && <div className="mt-2 h-1 rounded bg-raised"><div className="h-1 rounded bg-accent" style={{ width: `${p.progress * 100}%` }} /></div>}
                  </div>
                  {!p.item && (
                    <div className="flex items-center gap-2">
                      <Select className="h-8 w-44 py-1 text-xs" value={p.role} onChange={(e) => setFiles((cur) => cur.map((x) => (x === p ? { ...x, role: e.target.value as Pending["role"] } : x)))} aria-label="Evidence role">
                        <option value="primary">Primary evidence</option>
                        <option value="process_evidence">Process evidence (drafts, history)</option>
                      </Select>
                      <button className="rounded p-1.5 text-muted hover:text-danger" onClick={() => setFiles((cur) => cur.filter((x) => x !== p))} aria-label={`Remove ${p.file.name}`}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <Callout tone="slate" title="Recording a hash does not prove origin">
            The SHA-256 lets AEGIS detect any later change to the stored bytes. It says nothing about who created the file or whether it is authentic.
          </Callout>
          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => router.push(`/cases/${inv.id}`)}>Skip to case</Button>
            <div className="flex gap-2">
              <Button onClick={uploadAll} loading={busy} disabled={!files.some((f) => !f.item)} icon={<UploadCloud className="h-4 w-4" />}>Upload</Button>
              <Button variant="primary" disabled={!uploaded.length || busy} onClick={() => setStep(2)}>Continue</Button>
            </div>
          </div>
        </Panel>
      )}

      {step === 2 && inv && (
        <div className="space-y-5">
          {uploaded.filter((p) => p.item!.role === "primary").map((p) => {
            const prof = profiles.data?.find((x) => x.id === p.profile);
            const applicable = profiles.data?.filter((x) => x.modalities.includes(p.item!.modality)) ?? [];
            return (
              <Panel key={p.item!.id} title={p.item!.display_name} subtitle={`${p.item!.modality} · ${p.item!.mime_type}`}>
                <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
                  <div className="space-y-2">
                    {applicable.map((x) => (
                      <button key={x.id} onClick={() => setFiles((cur) => cur.map((f) => (f === p ? { ...f, profile: x.id } : f)))} className={cx("w-full rounded-lg border px-3 py-2.5 text-left text-sm", p.profile === x.id ? "border-accent/60 bg-accent/10" : "border-line hover:border-accent/30")}>
                        <div className="font-medium">{x.name}</div>
                        <div className="mt-0.5 text-xs text-muted">{x.methods.filter((m) => m.available).length} of {x.methods.length} methods operational</div>
                      </button>
                    ))}
                  </div>
                  {prof && (
                    <div>
                      <p className="text-sm text-muted">{prof.description}</p>
                      <p className="mt-1 text-xs text-muted">Estimated resources: {prof.resources}</p>
                      <ul className="mt-4 divide-y divide-line/50 rounded-lg border border-line/70">
                        {prof.methods.filter((m) => m.modalities.includes(p.item!.modality) || (p.item!.modality === "document" && m.modalities.includes("text"))).map((m) => (
                          <li key={m.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                            <span className={m.available ? "text-ink" : "text-muted"}>{m.name}</span>
                            {m.external_processing && <Badge tone="warn" title="Sends evidence outside this deployment">external</Badge>}
                            <span className="ml-auto flex gap-1.5"><EvidenceClassBadge value={m.evidence_class} /><ImplementationBadge value={m.implementation} available={m.available} /></span>
                            {!m.available && <span className="w-full text-xs text-muted">{m.reason}</span>}
                          </li>
                        ))}
                      </ul>
                      <ul className="mt-3 space-y-1 text-xs text-warn/90">
                        {prof.limitations.map((l) => <li key={l} className="flex gap-1.5"><ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />{l}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </Panel>
            );
          })}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => router.push(`/cases/${inv.id}`)}>Open case without analysis</Button>
            <Button variant="primary" loading={busy} onClick={runAnalyses} icon={<Play className="h-4 w-4" />}>Queue analyses</Button>
          </div>
        </div>
      )}
    </>
  );
}
