"use client";

import { Check, Copy, Info, Loader2, TriangleAlert, X } from "lucide-react";
import * as React from "react";

import { cx } from "@/lib/format";

/* ----------------------------------------------------------------------------- tones */

export const TONES: Record<string, string> = {
  slate: "bg-slate-500/10 text-slate-300 ring-slate-400/20",
  accent: "bg-accent/10 text-blue-300 ring-accent/30",
  cyan: "bg-cyan/10 text-cyan ring-cyan/30",
  violet: "bg-violet/10 text-violet ring-violet/30",
  ok: "bg-ok/10 text-ok ring-ok/30",
  warn: "bg-warn/10 text-warn ring-warn/30",
  danger: "bg-danger/10 text-danger ring-danger/30",
  ink: "bg-ink/10 text-ink ring-ink/25",
};

export const DOT: Record<string, string> = {
  slate: "bg-slate-400",
  accent: "bg-accent",
  cyan: "bg-cyan",
  violet: "bg-violet",
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  ink: "bg-ink",
};

export function Badge({
  tone = "slate",
  children,
  dot,
  className,
  title,
}: {
  tone?: string;
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset",
        TONES[tone] ?? TONES.slate,
        className,
      )}
    >
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full", DOT[tone] ?? DOT.slate)} />}
      {children}
    </span>
  );
}

/* ----------------------------------------------------------------------------- buttons */

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: React.ReactNode;
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  const styles = {
    primary:
      "bg-accent text-white shadow-glow hover:bg-blue-500 disabled:bg-accent/40 disabled:shadow-none",
    secondary: "border border-line bg-raised/70 text-ink hover:border-accent/50 hover:bg-raised",
    ghost: "text-muted hover:bg-raised/70 hover:text-ink",
    danger: "border border-danger/40 bg-danger/10 text-danger hover:bg-danger/20",
  }[variant];
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
        styles,
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

/* ----------------------------------------------------------------------------- layout */

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  icon,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  icon?: React.ReactNode;
}) {
  return (
    <section className={cx("panel animate-fadein", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line/70 px-5 py-3.5">
          <div className="flex min-w-0 items-start gap-2.5">
            {icon && <span className="mt-0.5 text-accent">{icon}</span>}
            <div className="min-w-0">
              {title && <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        {eyebrow && <div className="label mb-1.5">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "accent",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: string;
}) {
  return (
    <div className="panel relative overflow-hidden p-4">
      <div className={cx("absolute inset-x-0 top-0 h-px", DOT[tone])} style={{ opacity: 0.6 }} />
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        {icon && <span className="text-muted">{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function KV({ items, cols = 2 }: { items: [string, React.ReactNode][]; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={cx("grid gap-x-6 gap-y-3", cols === 1 ? "" : cols === 2 ? "sm:grid-cols-2" : "sm:grid-cols-3")}>
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="label">{k}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ----------------------------------------------------------------------------- feedback */

export function Callout({
  tone = "accent",
  title,
  children,
  icon,
}: {
  tone?: "accent" | "warn" | "danger" | "ok" | "violet" | "slate";
  title?: React.ReactNode;
  children?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  const Icon = tone === "warn" || tone === "danger" ? TriangleAlert : Info;
  return (
    <div className={cx("flex gap-3 rounded-lg px-4 py-3 text-sm ring-1 ring-inset", TONES[tone])} role="note">
      <span className="mt-0.5 shrink-0">{icon ?? <Icon className="h-4 w-4" aria-hidden />}</span>
      <div className="min-w-0">
        {title && <div className="font-medium text-ink">{title}</div>}
        {children && <div className={cx("leading-relaxed", title ? "mt-0.5 text-[13px] opacity-90" : "")}>{children}</div>}
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 py-12 text-center">
      {icon && <div className="mb-3 rounded-full border border-line bg-raised p-3 text-muted">{icon}</div>}
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {children && <p className="mt-1 max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-md bg-raised", className)} />;
}

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-8 text-sm text-muted" role="status">
      <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorBlock({ error }: { error: unknown }) {
  const e = error as { message?: string; correlationId?: string; status?: number };
  return (
    <Callout tone="danger" title={e?.status === 403 ? "Not permitted" : "Request failed"}>
      {e?.message ?? String(error)}
      {e?.correlationId && <span className="hash ml-2">ref {e.correlationId.slice(0, 8)}</span>}
    </Callout>
  );
}

/** Progress from real counts only. */
export function Progress({ done, total, active }: { done: number; total: number; active?: boolean }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-raised" aria-hidden>
        <div className="h-full rounded-full bg-gradient-to-r from-accent to-cyan transition-all" style={{ width: `${pct}%` }} />
        {active && <div className="absolute inset-y-0 w-1/3 animate-scan bg-gradient-to-r from-transparent via-white/15 to-transparent" />}
      </div>
      <span className="w-20 text-right text-xs tabular-nums text-muted">
        {done}/{total} methods
      </span>
    </div>
  );
}

/* ----------------------------------------------------------------------------- forms */

export function Field({
  label,
  hint,
  error,
  children,
  required,
}: {
  label: string;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  required?: boolean;
}) {
  const id = React.useId();
  const child = React.isValidElement(children)
    ? React.cloneElement(children as React.ReactElement<any>, {
        id,
        "aria-invalid": !!error,
        "aria-describedby": hint || error ? `${id}-d` : undefined,
      })
    : children;
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-ink/90">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      {child}
      {(error || hint) && (
        <p id={`${id}-d`} className={cx("mt-1 text-xs", error ? "text-danger" : "text-muted")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...p }, ref) {
    return <input ref={ref} className={cx("input", className)} {...p} />;
  },
);

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...p }, ref) {
    return <textarea ref={ref} className={cx("input min-h-[88px] resize-y", className)} {...p} />;
  },
);

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...p }, ref) {
    return (
      <select ref={ref} className={cx("input appearance-none pr-8", className)} {...p}>
        {children}
      </select>
    );
  },
);

/* ----------------------------------------------------------------------------- tabs */

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: React.ReactNode; count?: number }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line/70">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm transition-colors",
            value === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.label}
          {t.count != null && <span className="rounded bg-raised px-1.5 text-[11px] tabular-nums text-muted">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------------------- dialog */

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input,textarea,select,button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className={cx("panel max-h-[90vh] w-full overflow-auto", wide ? "max-w-3xl" : "max-w-lg")}
      >
        <div className="flex items-center justify-between border-b border-line/70 px-5 py-3.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-raised hover:text-ink" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line/70 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------------------- hash */

export function Hash({ value, short = false, className }: { value: string | null | undefined; short?: boolean; className?: string }) {
  const [copied, setCopied] = React.useState(false);
  if (!value) return <span className="hash">—</span>;
  return (
    <span className={cx("group inline-flex max-w-full items-center gap-1.5", className)}>
      <code className="hash truncate" title={value}>
        {short ? `${value.slice(0, 12)}…${value.slice(-6)}` : value}
      </code>
      <button
        type="button"
        aria-label="Copy hash"
        className="shrink-0 text-muted opacity-60 hover:text-ink group-hover:opacity-100"
        onClick={() => {
          navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          });
        }}
      >
        {copied ? <Check className="h-3.5 w-3.5 text-ok" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </span>
  );
}

/* ----------------------------------------------------------------------------- simple table */

export function SimpleTable({
  columns,
  rows,
  empty,
  onRowClick,
  dense,
}: {
  columns: { key: string; header: React.ReactNode; className?: string; render?: (row: any) => React.ReactNode }[];
  rows: any[];
  empty?: React.ReactNode;
  onRowClick?: (row: any) => void;
  dense?: boolean;
}) {
  if (!rows.length) return <>{empty ?? <p className="py-6 text-center text-sm text-muted">No records.</p>}</>;
  return (
    <div className="-mx-5 overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-line/70">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cx("label px-5 py-2 font-medium", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/50">
          {rows.map((r, i) => (
            <tr
              key={r.id ?? r.seq ?? i}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(r) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              className={cx("transition-colors", onRowClick && "cursor-pointer hover:bg-raised/50")}
            >
              {columns.map((c) => (
                <td key={c.key} className={cx("px-5 align-top", dense ? "py-2" : "py-3", c.className)}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
