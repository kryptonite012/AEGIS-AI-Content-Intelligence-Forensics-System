"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, KeyRound, SlidersHorizontal, UserPlus, Users } from "lucide-react";
import * as React from "react";

import { EvidenceClassBadge, ImplementationBadge } from "@/components/badges";
import { Badge, Button, Callout, Dialog, ErrorBlock, Field, Input, KV, LoadingBlock, PageHeader, Panel, Select, SimpleTable, Tabs, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum, humanize } from "@/lib/format";

const ROLES = ["org_admin", "investigator", "forensic_analyst", "independent_reviewer", "auditor", "researcher"];

function UsersTab() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<any[]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<{ roles: any[] }>("/roles") });
  const [open, setOpen] = React.useState(false);
  const [v, setV] = React.useState({ email: "", display_name: "", password: "", role: "investigator" });
  const [err, setErr] = React.useState<string | null>(null);
  const create = async () => {
    setErr(null);
    try {
      await api("/users", { json: v });
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  const patch = useMutation({ mutationFn: ({ id, body }: { id: string; body: any }) => api(`/users/${id}`, { method: "PATCH", json: body }), onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }), onError: (e) => setErr((e as Error).message) });
  return (
    <div className="space-y-6">
      <Panel title="Members" icon={<Users className="h-4 w-4" />} actions={<Button size="sm" variant="primary" onClick={() => setOpen(true)} icon={<UserPlus className="h-3.5 w-3.5" />}>Add member</Button>}>
        {err && <div className="mb-3"><Callout tone="danger">{err}</Callout></div>}
        {users.isLoading ? <LoadingBlock /> : (
          <SimpleTable rows={users.data ?? []} columns={[
            { key: "name", header: "Name", render: (u) => <div><div className="font-medium">{u.display_name}</div><div className="text-xs text-muted">{u.email}</div></div> },
            { key: "role", header: "Role", render: (u) => u.id === me?.id ? <Badge tone="accent">{u.role_name}</Badge> : (
              <Select className="h-8 w-52 py-1 text-xs" value={u.role} onChange={(e) => patch.mutate({ id: u.id, body: { role: e.target.value } })} aria-label={`Role for ${u.email}`}>
                {ROLES.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
              </Select>
            ) },
            { key: "mfa", header: "MFA", render: (u) => <Badge tone={u.mfa_enabled ? "ok" : "slate"}>{u.mfa_enabled ? "enabled" : "off"}</Badge> },
            { key: "status", header: "Status", render: (u) => <Badge tone={u.is_active ? "ok" : "danger"} dot>{u.is_active ? "active" : "deactivated"}</Badge> },
            { key: "last", header: "Last sign-in", render: (u) => <span className="text-xs text-muted">{fmtDate(u.last_login_at)}</span> },
            { key: "act", header: "", render: (u) => u.id !== me?.id && (
              <div className="flex justify-end gap-1.5">
                <Button size="sm" variant="ghost" onClick={() => api(`/users/${u.id}/revoke-sessions`, { method: "POST" })}>Revoke sessions</Button>
                <Button size="sm" variant={u.is_active ? "danger" : "secondary"} onClick={() => patch.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? "Deactivate" : "Reactivate"}</Button>
              </div>
            ) },
          ]} />
        )}
      </Panel>
      <Panel title="Roles and permissions" subtitle="Enforced on the server for every request">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {roles.data?.roles.map((r) => (
            <div key={r.id} className="rounded-lg border border-line/70 bg-bg/40 p-4">
              <div className="text-sm font-semibold">{r.name}</div>
              <p className="mt-1 text-xs text-muted">{r.description}</p>
              <div className="mt-3 flex flex-wrap gap-1">{r.permissions.map((p: string) => <code key={p} className="rounded bg-raised px-1.5 py-0.5 font-mono text-[10.5px] text-ink/80">{p}</code>)}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Dialog open={open} onClose={() => setOpen(false)} title="Add organisation member" footer={<Button variant="primary" onClick={create}>Create</Button>}>
        <Field label="Email"><Input type="email" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} /></Field>
        <Field label="Display name"><Input value={v.display_name} onChange={(e) => setV({ ...v, display_name: e.target.value })} /></Field>
        <Field label="Initial password" hint="At least 12 characters, mixed case and a digit. Ask the user to change it."><Input type="password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} /></Field>
        <Field label="Role"><Select value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}</Select></Field>
        {err && <Callout tone="danger">{err}</Callout>}
      </Dialog>
    </div>
  );
}

function ModelsTab() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const models = useQuery({ queryKey: ["models"], queryFn: () => api<any[]>("/models") });
  const profiles = useQuery({ queryKey: ["cal-profiles"], queryFn: () => api<any[]>("/benchmarks/calibration-profiles") });
  const runs = useQuery({ queryKey: ["bench-runs"], queryFn: () => api<any[]>("/benchmarks/runs") });
  const [edit, setEdit] = React.useState<any | null>(null);
  const [form, setForm] = React.useState<any>({});
  const [err, setErr] = React.useState<string | null>(null);
  const save = async () => {
    setErr(null);
    try {
      const body: any = { reason: form.reason, enabled: form.enabled, license: form.license || null, validation_status: form.validation_status };
      if (form.validation_benchmark_run_id) body.validation_benchmark_run_id = form.validation_benchmark_run_id;
      if (form.calibration_profile_id) body.calibration_profile_id = form.calibration_profile_id;
      if (form.languages) body.languages_evaluated = form.languages.split(",").map((s: string) => s.trim()).filter(Boolean);
      await api(`/models/${edit.id}`, { method: "PATCH", json: body });
      setEdit(null);
      qc.invalidateQueries({ queryKey: ["models"] });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  if (models.isLoading) return <LoadingBlock />;
  if (models.error) return <ErrorBlock error={models.error} />;
  return (
    <Panel title="Model and detector registry" subtitle="A detector can only be marked validated with a completed, locally measured benchmark run. All changes are audited." icon={<Cpu className="h-4 w-4" />}>
      <SimpleTable rows={models.data ?? []} columns={[
        { key: "name", header: "Method", render: (m) => <div><div className="font-medium">{m.name}</div><div className="font-mono text-[11px] text-muted">{m.method_id} v{m.version}</div></div> },
        { key: "class", header: "Evidence class", render: (m) => <EvidenceClassBadge value={m.evidence_class} /> },
        { key: "impl", header: "Operational", render: (m) => <span title={m.availability_reason}><ImplementationBadge value={m.implementation_status} available={m.operational} /></span> },
        { key: "val", header: "Validation", render: (m) => <Badge tone={m.validation_status === "validated" ? "ok" : m.validation_status === "deprecated" ? "danger" : "slate"}>{m.validation_status}</Badge> },
        { key: "langs", header: "Languages evaluated", render: (m) => <span className="text-xs text-muted">{m.languages_evaluated?.join(", ") || "none"}</span> },
        { key: "bench", header: "Last benchmark", render: (m) => m.last_benchmark ? <span className="text-xs">{humanize(m.last_benchmark.result_kind)} · AUROC {fmtNum(m.last_benchmark.auroc)}</span> : <span className="text-xs text-muted">none</span> },
        { key: "en", header: "Enabled", render: (m) => <Badge tone={m.enabled ? "ok" : "slate"}>{m.enabled ? "yes" : "disabled"}</Badge> },
        { key: "e", header: "", render: (m) => can("admin.models") && <Button size="sm" variant="ghost" onClick={() => { setEdit(m); setForm({ enabled: m.enabled, license: m.license ?? "", validation_status: m.validation_status, languages: (m.languages_evaluated || []).join(", "), reason: "" }); }}>Edit</Button> },
      ]} />
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={`Registry: ${edit?.name}`} wide footer={<Button variant="primary" disabled={(form.reason ?? "").length < 10} onClick={save}>Save (audited)</Button>}>
        {edit && <KV cols={2} items={[["Supported media", edit.supported_media.join(", ")], ["Minimum input", JSON.stringify(edit.minimum_input)], ["Provider", edit.provider_id], ["Documentation", edit.data_documentation ?? "—"]]} />}
        {edit && <div><div className="label mb-1">Known limitations</div><ul className="list-disc space-y-1 pl-5 text-xs text-muted">{edit.known_limitations.map((l: string) => <li key={l}>{l}</li>)}</ul></div>}
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Enabled"><Select value={String(form.enabled)} onChange={(e) => setForm({ ...form, enabled: e.target.value === "true" })}><option value="true">Enabled</option><option value="false">Disabled</option></Select></Field>
          <Field label="Licence"><Input value={form.license} onChange={(e) => setForm({ ...form, license: e.target.value })} /></Field>
          <Field label="Validation status"><Select value={form.validation_status} onChange={(e) => setForm({ ...form, validation_status: e.target.value })}><option value="unvalidated">Unvalidated</option><option value="validated">Validated</option><option value="deprecated">Deprecated</option></Select></Field>
          <Field label="Languages evaluated (comma-separated)"><Input value={form.languages} onChange={(e) => setForm({ ...form, languages: e.target.value })} /></Field>
          <Field label="Supporting benchmark run"><Select value={form.validation_benchmark_run_id ?? ""} onChange={(e) => setForm({ ...form, validation_benchmark_run_id: e.target.value })}><option value="">—</option>{runs.data?.filter((r) => r.method_id === edit?.method_id).map((r) => <option key={r.id} value={r.id}>{humanize(r.result_kind)} · {fmtDate(r.created_at)}</option>)}</Select></Field>
          <Field label="Calibration profile"><Select value={form.calibration_profile_id ?? ""} onChange={(e) => setForm({ ...form, calibration_profile_id: e.target.value })}><option value="">—</option>{profiles.data?.filter((p) => p.method_id === edit?.method_id).map((p) => <option key={p.id} value={p.id}>{p.validated ? "validated" : "NOT validated"} · FPR {p.target_fpr}</option>)}</Select></Field>
        </div>
        <Field label="Reason for change" hint="Recorded in the audit trail (at least 10 characters)."><Textarea value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        {err && <Callout tone="danger">{err}</Callout>}
      </Dialog>
    </Panel>
  );
}

function SettingsTab() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: () => api<any>("/admin/settings") });
  const retention = useQuery({ queryKey: ["retention"], queryFn: () => api<any>("/admin/retention") });
  const [reason, setReason] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const [edit, setEdit] = React.useState<any | null>(null);
  const toggleExternal = async () => {
    setErr(null);
    try {
      await api("/organizations/current/settings", { method: "PUT", json: { allow_external_processing: !me?.organization.allow_external_processing, reason } });
      window.location.reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Runtime configuration" subtitle="From environment variables; secrets are never displayed" icon={<SlidersHorizontal className="h-4 w-4" />}>
          {settings.data && <KV cols={2} items={Object.entries(settings.data.runtime).map(([k, v]) => [humanize(k), String(v)])} />}
          <p className="mt-4 text-xs text-muted">{settings.data?.note}</p>
        </Panel>
        <Panel title="External processing" subtitle="Evidence leaves the deployment only if the deployment, the organisation and the case all allow it" icon={<KeyRound className="h-4 w-4" />}>
          <KV items={[["Deployment kill switch", settings.data?.runtime.allow_external_processing ? "allows" : "blocks"], ["This organisation", me?.organization.allow_external_processing ? "allows" : "blocks"]]} />
          <div className="mt-4 space-y-2">
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (recorded in the audit trail)" />
            <Button variant={me?.organization.allow_external_processing ? "danger" : "secondary"} disabled={reason.length < 10} onClick={toggleExternal}>{me?.organization.allow_external_processing ? "Block external processing" : "Allow external processing"}</Button>
            {err && <Callout tone="danger">{err}</Callout>}
          </div>
        </Panel>
      </div>
      <Panel title="Retention policies" subtitle="Templates require review by your organisation; deletion always needs two people and is blocked under legal hold">
        <SimpleTable rows={(retention.data?.policies ?? []).map((p: any) => ({ id: p.classification, ...p }))} columns={[
          { key: "classification", header: "Classification", render: (p) => humanize(p.classification) },
          { key: "days", header: "Retain (days)", render: (p) => p.retain_days },
          { key: "desc", header: "Description", render: (p) => <span className="text-xs text-muted">{p.description || "—"}</span> },
          { key: "e", header: "", render: (p) => <Button size="sm" variant="ghost" onClick={() => setEdit({ ...p, reason: "" })}>Edit</Button> },
        ]} />
        {!!retention.data?.due_for_review?.length && <div className="mt-4"><Callout tone="warn" title={`${retention.data.due_for_review.length} case(s) past their retention period`}>{retention.data.due_for_review.map((d: any) => d.case_reference).join(", ")}</Callout></div>}
      </Panel>
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={`Retention: ${humanize(edit?.classification)}`} footer={<Button variant="primary" onClick={async () => { await api(`/admin/retention/${edit.classification}`, { method: "PUT", json: { retain_days: Number(edit.retain_days), description: edit.description, reason: edit.reason } }); setEdit(null); qc.invalidateQueries({ queryKey: ["retention"] }); }}>Save</Button>}>
        <Field label="Retain (days)"><Input type="number" value={edit?.retain_days ?? 0} onChange={(e) => setEdit({ ...edit, retain_days: e.target.value })} /></Field>
        <Field label="Description"><Textarea value={edit?.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
        <Field label="Reason"><Input value={edit?.reason ?? ""} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} /></Field>
      </Dialog>
    </div>
  );
}

export default function AdminPage() {
  const [tab, setTab] = React.useState<"users" | "models" | "settings">("users");
  return (
    <>
      <PageHeader eyebrow="Governance" title={<span className="flex items-center gap-3"><SlidersHorizontal className="h-6 w-6 text-accent" /> Administration</span>} description="Users and roles, the model registry, calibration and validation records, organisation settings and retention." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "users", label: "Users & roles" }, { id: "models", label: "Model registry" }, { id: "settings", label: "Settings & retention" }]} />
      <div className="mt-6">
        {tab === "users" && <UsersTab />}
        {tab === "models" && <ModelsTab />}
        {tab === "settings" && <SettingsTab />}
      </div>
    </>
  );
}
