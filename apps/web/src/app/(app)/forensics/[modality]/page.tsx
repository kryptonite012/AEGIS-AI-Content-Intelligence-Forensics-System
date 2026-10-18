"use client";

import type { EvidenceListItem } from "@aegis/shared-types";
import { useQuery } from "@tanstack/react-query";
import { AudioWaveform, Clapperboard, FileText, Image as ImageIcon } from "lucide-react";
import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import * as React from "react";

import { JobView } from "@/components/analysis";
import { DemoBadge, OutcomeBadge } from "@/components/badges";
import { MethodCapabilities } from "@/components/methods";
import { Callout, EmptyState, ErrorBlock, Hash, Input, LoadingBlock, PageHeader, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { cx, fmtBytes, fmtRelative } from "@/lib/format";

const META: Record<string, { title: string; icon: React.ElementType; modalities: string; methodModality: string; intro: string; cautions: string[] }> = {
  text: {
    title: "Text forensics",
    icon: FileText,
    modalities: "text,document",
    methodModality: "text",
    intro: "Extraction, segmentation and language identification, supervised and zero-shot detectors where configured, and watermark verification.",
    cautions: [
      "No detector can reliably establish authorship from text alone; a low score does not prove human authorship.",
      "Short texts (< 50 tokens), non-native writing, translation and heavy editing all degrade reliability.",
      "Sentence-level scores, where validated, do not establish who wrote each sentence.",
    ],
  },
  image: {
    title: "Image forensics",
    icon: ImageIcon,
    modalities: "image",
    methodModality: "image",
    intro: "Structure and metadata, Content Credentials, frequency spectrum, noise residual and error-level views, plus configured models.",
    cautions: [
      "Forensic visualisations are observations for an analyst — none is a classifier.",
      "Anatomical oddities are not used as a detector; saliency maps are not proof that a region is synthetic.",
    ],
  },
  audio: {
    title: "Audio forensics",
    icon: AudioWaveform,
    modalities: "audio",
    methodModality: "audio",
    intro: "Container inspection, waveform and spectrogram, signal-quality observations, provenance and configured synthetic-speech models.",
    cautions: [
      "AEGIS never infers a speaker's identity, nationality, ethnicity, intent or criminality.",
      "Transcription (if configured) is a separate service; transcription errors are not authenticity findings.",
    ],
  },
  video: {
    title: "Video forensics",
    icon: Clapperboard,
    modalities: "video",
    methodModality: "video",
    intro: "Container and stream inspection, keyframes, sampled-frame temporal consistency, audio-track analysis and container-level A/V alignment.",
    cautions: [
      "A synthetic-looking frame does not show that a whole video is fabricated.",
      "No facial recognition or identity judgement is performed.",
    ],
  },
};

export default function ModalityPage() {
  const { modality } = useParams<{ modality: string }>();
  const meta = META[modality];
  const [q, setQ] = React.useState("");
  const [selected, setSelected] = React.useState<EvidenceListItem | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["evidence", "modality", modality, q],
    queryFn: () => api<EvidenceListItem[]>(`/evidence?modality=${meta.modalities}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
    enabled: !!meta,
  });
  React.useEffect(() => {
    if (!selected && data?.length) setSelected(data.find((d) => d.latest_job) ?? data[0]);
  }, [data, selected]);
  if (!meta) notFound();
  const Icon = meta.icon;
  return (
    <>
      <PageHeader eyebrow="Forensics" title={<span className="flex items-center gap-3"><Icon className="h-6 w-6 text-accent" /> {meta.title}</span>} description={meta.intro} />
      <div className="mb-6 grid gap-3 md:grid-cols-3">
        {meta.cautions.map((c) => <Callout key={c} tone="slate">{c}</Callout>)}
      </div>
      <div className="grid gap-6 xl:grid-cols-[340px_1fr]">
        <Panel title="Evidence" subtitle="Across cases visible to you" bodyClassName="p-3">
          <Input placeholder="Filter by name or SHA-256 prefix" value={q} onChange={(e) => setQ(e.target.value)} className="mb-3" aria-label="Filter evidence" />
          {error ? <ErrorBlock error={error} /> : isLoading ? <LoadingBlock /> : !data?.length ? (
            <EmptyState title={`No ${modality} evidence`}>Acquire evidence through a case to analyse it here.</EmptyState>
          ) : (
            <ul className="max-h-[70vh] space-y-1 overflow-auto">
              {data.map((e) => (
                <li key={e.id}>
                  <button onClick={() => setSelected(e)} className={cx("w-full rounded-lg px-3 py-2.5 text-left", selected?.id === e.id ? "bg-accent/10 ring-1 ring-accent/30" : "hover:bg-raised/60")}>
                    <div className="flex items-center gap-2"><span className="truncate text-sm">{e.display_name}</span><DemoBadge show={e.is_demo_fixture} /></div>
                    <div className="mt-1"><OutcomeBadge value={e.latest_job?.primary_outcome} label={e.latest_job?.primary_label} /></div>
                    <div className="mt-1 text-[11px] text-muted">{e.mime_type} · {fmtBytes(e.size_bytes)} · {fmtRelative(e.acquired_at)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <div className="min-w-0 space-y-6">
          {selected && (
            <Panel
              title={selected.display_name}
              subtitle={<span className="flex items-center gap-2">SHA-256 <Hash value={selected.sha256} short /></span>}
              actions={<Link className="text-xs text-accent hover:underline" href={`/cases/${selected.investigation_id}?evidence=${selected.id}`}>Open in case</Link>}
            >
              {selected.latest_job ? <JobView jobId={selected.latest_job.id} /> : <EmptyState title="Not yet analysed">Run an analysis from the case to see results here.</EmptyState>}
            </Panel>
          )}
          <MethodCapabilities modality={meta.methodModality} />
        </div>
      </div>
    </>
  );
}
