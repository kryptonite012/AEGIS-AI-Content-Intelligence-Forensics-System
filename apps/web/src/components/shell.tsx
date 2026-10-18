"use client";

import type { HealthComponent, Notification } from "@aegis/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AudioWaveform,
  Bell,
  BookCheck,
  Building2,
  ChevronDown,
  Clapperboard,
  FileSearch,
  FileText,
  FlaskConical,
  FolderKanban,
  Image as ImageIcon,
  LayoutDashboard,
  LogOut,
  Menu,
  Microscope,
  PlusCircle,
  ScrollText,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Stamp,
  Vault,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, fmtRelative } from "@/lib/format";

type NavItem = { href: string; label: string; icon: React.ElementType; perm?: string };

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Operations",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard, perm: "case.read" },
      { href: "/investigations/new", label: "New Investigation", icon: PlusCircle, perm: "case.create" },
      { href: "/cases", label: "Case Files", icon: FolderKanban, perm: "case.read" },
    ],
  },
  {
    group: "Forensics",
    items: [
      { href: "/forensics/text", label: "Text Forensics", icon: FileText, perm: "analysis.read" },
      { href: "/forensics/image", label: "Image Forensics", icon: ImageIcon, perm: "analysis.read" },
      { href: "/forensics/audio", label: "Audio Forensics", icon: AudioWaveform, perm: "analysis.read" },
      { href: "/forensics/video", label: "Video Forensics", icon: Clapperboard, perm: "analysis.read" },
      { href: "/provenance", label: "Provenance & Watermarks", icon: Stamp, perm: "analysis.read" },
      { href: "/evidence", label: "Evidence Vault", icon: Vault, perm: "evidence.read" },
    ],
  },
  {
    group: "Science",
    items: [
      { href: "/research", label: "Research Bench", icon: Microscope, perm: "research.use" },
      { href: "/benchmarks", label: "Benchmark Laboratory", icon: FlaskConical, perm: "benchmark.read" },
    ],
  },
  {
    group: "Governance",
    items: [
      { href: "/reports", label: "Reports", icon: ScrollText, perm: "report.read" },
      { href: "/audit", label: "Audit & Compliance", icon: BookCheck, perm: "case.read" },
      { href: "/admin", label: "Administration", icon: SlidersHorizontal, perm: "admin.users" },
      { href: "/health", label: "System Health", icon: Activity, perm: "system.health" },
    ],
  },
];

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 64 64" className="h-8 w-8 shrink-0" aria-hidden>
        <defs>
          <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3B82F6" />
            <stop offset="1" stopColor="#22D3EE" />
          </linearGradient>
        </defs>
        <path d="M32 6 54 15v16c0 13.5-9 23.4-22 27-13-3.6-22-13.5-22-27V15Z" fill="rgb(11 17 30)" stroke="url(#lg)" strokeWidth="3" strokeLinejoin="round" />
        <path d="M22 39 32 19l10 20M26 32h12" fill="none" stroke="#E2E8F4" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {!compact && (
        <div className="leading-none">
          <div className="text-[15px] font-semibold tracking-[0.18em] text-ink">AEGIS</div>
          <div className="mt-1 text-[9.5px] uppercase tracking-[0.14em] text-muted">Forensic Intelligence</div>
        </div>
      )}
    </div>
  );
}

const MODE_TONE: Record<string, string> = { demo: "warn", research: "violet", "connected-production": "ok" };
const MODE_LABEL: Record<string, string> = { demo: "Demo", research: "Research", "connected-production": "Connected-Production" };

function useHealth(enabled: boolean) {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ components: HealthComponent[]; methods: { available: boolean; implementation: string }[] }>("/health/components"),
    enabled,
    refetchInterval: 30_000,
  });
}

function HealthIndicator() {
  const { can } = useAuth();
  const { data } = useHealth(can("system.health"));
  if (!data) return null;
  const down = data.components.filter((c) => c.status === "unavailable");
  const methodsDown = data.methods.filter((m) => !m.available).length;
  return (
    <Link
      href="/health"
      className={cx(
        "hidden items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs lg:flex",
        down.length ? "border-danger/40 bg-danger/10 text-danger" : "border-line bg-raised/50 text-muted hover:text-ink",
      )}
      title={down.map((d) => `${d.name}: ${d.detail}`).join("\n") || "All infrastructure components operational"}
    >
      <span className={cx("h-2 w-2 rounded-full", down.length ? "bg-danger" : "bg-ok")} />
      {down.length ? `${down.length} component${down.length > 1 ? "s" : ""} down` : "Infrastructure operational"}
      <span className="text-muted">· {methodsDown} methods unavailable</span>
    </Link>
  );
}

function GlobalSearch() {
  const [q, setQ] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const { data } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api<{ investigations: any[]; evidence: any[] }>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
  });
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const go = (href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  };
  return (
    <div className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search cases, evidence names or SHA-256…"
        aria-label="Global search"
        className="input h-9 pl-9 pr-14"
      />
      <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-line px-1.5 text-[10px] text-muted">
        Ctrl K
      </kbd>
      {open && q.trim().length >= 2 && data && (
        <div className="panel absolute left-0 right-0 top-11 z-40 max-h-96 overflow-auto p-2">
          {!data.investigations.length && !data.evidence.length && <p className="p-3 text-sm text-muted">No matches.</p>}
          {data.investigations.map((i) => (
            <button key={i.id} onMouseDown={() => go(`/cases/${i.id}`)} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-raised">
              <FolderKanban className="h-4 w-4 text-accent" />
              <span className="font-mono text-xs text-muted">{i.case_reference}</span>
              <span className="truncate text-sm">{i.title}</span>
            </button>
          ))}
          {data.evidence.map((e) => (
            <button key={e.id} onMouseDown={() => go(`/cases/${e.investigation_id}?evidence=${e.id}`)} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-raised">
              <FileSearch className="h-4 w-4 text-cyan" />
              <span className="truncate text-sm">{e.display_name}</span>
              <Badge>{e.modality}</Badge>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const [open, setOpen] = React.useState(false);
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<{ unread: number; items: Notification[] }>("/notifications"),
    refetchInterval: 20_000,
  });
  const markAll = async () => {
    await api("/notifications/read", { method: "POST", json: [] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  const sev: Record<string, string> = { info: "accent", warning: "warn", error: "danger", critical: "danger" };
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg border border-line bg-raised/50 p-2 text-muted hover:text-ink"
        aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ""}`}
      >
        <Bell className="h-4 w-4" />
        {!!data?.unread && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-white">
            {data.unread}
          </span>
        )}
      </button>
      {open && (
        <div className="panel absolute right-0 top-11 z-40 w-96 overflow-hidden">
          <div className="flex items-center justify-between border-b border-line/70 px-4 py-2.5">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-accent hover:underline" onClick={markAll}>
              Mark all read
            </button>
          </div>
          <div className="max-h-[420px] divide-y divide-line/50 overflow-auto">
            {!data?.items.length && <p className="p-6 text-center text-sm text-muted">Nothing yet. Job, review and integrity events appear here.</p>}
            {data?.items.map((n) => (
              <Link key={n.id} href={n.link || "#"} onClick={() => setOpen(false)} className={cx("block px-4 py-3 hover:bg-raised/60", !n.read_at && "bg-accent/[0.04]")}>
                <div className="flex items-center gap-2">
                  <Badge tone={sev[n.severity]} dot>
                    {n.kind.replace(/_/g, " ")}
                  </Badge>
                  <span className="ml-auto text-[11px] text-muted">{fmtRelative(n.created_at)}</span>
                </div>
                <div className="mt-1.5 text-sm text-ink">{n.title}</div>
                {n.body && <div className="mt-0.5 line-clamp-2 text-xs text-muted">{n.body}</div>}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { me, signOut, switchOrganization } = useAuth();
  const [open, setOpen] = React.useState(false);
  if (!me) return null;
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2.5 rounded-lg border border-line bg-raised/50 py-1 pl-1 pr-2.5 hover:border-accent/40" aria-haspopup="menu">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-accent to-violet text-xs font-semibold text-white">
          {me.display_name.split(" ").map((s) => s[0]).slice(0, 2).join("")}
        </span>
        <span className="hidden text-left leading-tight md:block">
          <span className="block text-xs font-medium">{me.display_name}</span>
          <span className="block text-[11px] text-muted">{me.role_name}</span>
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-muted" />
      </button>
      {open && (
        <div className="panel absolute right-0 top-11 z-40 w-72 p-2" role="menu">
          <div className="px-3 py-2">
            <div className="text-sm font-medium">{me.email}</div>
            <div className="text-xs text-muted">MFA {me.mfa_enabled ? "enabled" : "not enabled"}</div>
          </div>
          <div className="label px-3 pt-2">Workspace</div>
          {me.memberships.map((m) => (
            <button
              key={m.organization_id}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                switchOrganization(m.organization_id);
              }}
              className={cx("flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-raised", m.organization_id === me.organization.id && "text-accent")}
            >
              <Building2 className="h-4 w-4" /> <span className="truncate">{m.organization_name}</span>
              <span className="ml-auto text-[11px] text-muted">{m.role_name}</span>
            </button>
          ))}
          <div className="my-2 border-t border-line/70" />
          <button role="menuitem" onClick={signOut} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-danger hover:bg-danger/10">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading, can } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  React.useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, me, router, pathname]);
  React.useEffect(() => setMobileOpen(false), [pathname]);

  if (loading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4 text-sm text-muted">
          <Logo />
          <div className="h-0.5 w-40 overflow-hidden rounded bg-raised">
            <div className="h-full w-1/3 animate-scan bg-gradient-to-r from-transparent via-accent to-transparent" />
          </div>
        </div>
      </div>
    );
  }
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  const nav = (
    <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5" aria-label="Primary">
      {NAV.map((g) => {
        const items = g.items.filter((i) => !i.perm || can(i.perm));
        if (!items.length) return null;
        return (
          <div key={g.group}>
            <div className="label mb-2 px-3">{g.group}</div>
            <ul className="space-y-0.5">
              {items.map((i) => (
                <li key={i.href}>
                  <Link
                    href={i.href}
                    aria-current={isActive(i.href) ? "page" : undefined}
                    className={cx(
                      "group flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition-colors",
                      isActive(i.href) ? "bg-accent/10 text-ink ring-1 ring-inset ring-accent/25" : "text-muted hover:bg-raised/70 hover:text-ink",
                    )}
                  >
                    <i.icon className={cx("h-4 w-4", isActive(i.href) ? "text-accent" : "text-muted group-hover:text-ink")} aria-hidden />
                    {i.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
  const mode = me.environment.mode;
  return (
    <div className="aegis-backdrop flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line/70 bg-surface/80 backdrop-blur lg:flex">
        <div className="flex h-16 items-center border-b border-line/70 px-5">
          <Link href="/" aria-label="AEGIS overview">
            <Logo />
          </Link>
        </div>
        {nav}
        <div className="border-t border-line/70 p-4 text-[11px] leading-relaxed text-muted">
          <div className="flex items-center gap-2 text-ink/80">
            <ShieldCheck className="h-3.5 w-3.5 text-ok" /> Defensive forensic use only
          </div>
          <p className="mt-1">Detector outputs start a review; they never establish misconduct.</p>
        </div>
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex w-72 flex-col border-r border-line bg-surface">
            <div className="flex h-16 items-center justify-between border-b border-line/70 px-5">
              <Logo />
              <button onClick={() => setMobileOpen(false)} aria-label="Close menu" className="text-muted">
                <X className="h-5 w-5" />
              </button>
            </div>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line/70 bg-bg/80 px-4 backdrop-blur md:px-6">
          <button className="rounded-lg p-2 text-muted hover:text-ink lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-2.5">
            <HealthIndicator />
            <Badge tone={MODE_TONE[mode]} dot title="Deployment mode">
              {MODE_LABEL[mode]} mode
            </Badge>
            <span className="hidden max-w-[180px] truncate rounded-lg border border-line bg-raised/50 px-2.5 py-1.5 text-xs text-muted xl:inline" title="Current workspace">
              <Building2 className="mr-1.5 inline h-3.5 w-3.5" />
              {me.organization.name}
            </span>
            <Notifications />
            <UserMenu />
          </div>
        </header>
        {mode === "demo" && (
          <div className="border-b border-warn/20 bg-warn/[0.06] px-6 py-1.5 text-center text-[12px] text-warn">
            Demo mode — cases marked DEMO FIXTURE contain synthetic data only. No figures on this system describe a real deployment.
          </div>
        )}
        <main id="main" className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-6 md:px-8 md:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
