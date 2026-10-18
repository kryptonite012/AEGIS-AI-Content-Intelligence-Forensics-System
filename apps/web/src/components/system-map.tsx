"use client";

import type { HealthComponent } from "@aegis/shared-types";
import { Archive, Cpu, Database, FileCheck2, Inbox, Layers, ShieldCheck, Stamp } from "lucide-react";
import * as React from "react";

import { cx } from "@/lib/format";

type Node = { id: string; label: string; icon: React.ElementType; sources: string[] };

// Logical processing pipeline (not geographic). Status of each node comes from real health checks.
const NODES: Node[] = [
  { id: "intake", label: "Evidence intake", icon: Inbox, sources: ["malware_scanner"] },
  { id: "storage", label: "Evidence storage", icon: Archive, sources: ["storage"] },
  { id: "db", label: "Case database", icon: Database, sources: ["database"] },
  { id: "queue", label: "Processing queue", icon: Layers, sources: ["redis", "queue"] },
  { id: "workers", label: "Model services", icon: Cpu, sources: ["worker", "ffmpeg"] },
  { id: "provenance", label: "Provenance verification", icon: Stamp, sources: ["c2pa"] },
  { id: "reports", label: "Reports & audit", icon: FileCheck2, sources: ["database", "storage"] },
];

function nodeStatus(n: Node, comps: Record<string, HealthComponent>) {
  const st = n.sources.map((s) => comps[s]?.status).filter(Boolean);
  if (!st.length) return "unknown";
  if (st.includes("unavailable")) return "unavailable";
  if (st.includes("unknown")) return "partial";
  return "operational";
}

const TONE: Record<string, string> = {
  operational: "border-ok/40 text-ok",
  partial: "border-warn/40 text-warn",
  unavailable: "border-danger/50 text-danger",
  unknown: "border-line text-muted",
};

export function SystemMap({ components, methodsAvailable, methodsTotal }: { components: HealthComponent[]; methodsAvailable: number; methodsTotal: number }) {
  const comps = Object.fromEntries(components.map((c) => [c.id, c]));
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
        {NODES.map((n, i) => {
          const s = nodeStatus(n, comps);
          const detail = n.sources.map((x) => comps[x] && `${comps[x].name}: ${comps[x].detail}`).filter(Boolean).join("\n");
          return (
            <div key={n.id} className="relative" title={detail}>
              {i < NODES.length - 1 && <div className="absolute left-[calc(50%+28px)] right-[-12px] top-7 hidden h-px bg-gradient-to-r from-line to-line/30 xl:block" />}
              <div className="flex flex-col items-center text-center">
                <div className={cx("relative flex h-14 w-14 items-center justify-center rounded-2xl border bg-raised/70", TONE[s])}>
                  <n.icon className="h-6 w-6" aria-hidden />
                  <span className={cx("absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-surface", s === "operational" ? "bg-ok" : s === "partial" ? "bg-warn" : s === "unavailable" ? "bg-danger" : "bg-slate-500")} />
                </div>
                <div className="mt-2 text-xs font-medium text-ink">{n.label}</div>
                <div className={cx("text-[11px] capitalize", TONE[s].split(" ")[1])}>{s === "partial" ? "partially configured" : s}</div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-4 flex items-center gap-2 text-xs text-muted">
        <ShieldCheck className="h-3.5 w-3.5 text-ok" />
        {methodsAvailable} of {methodsTotal} analysis methods are operational in this environment; the remainder are explicitly unavailable until configured.
      </div>
    </div>
  );
}
