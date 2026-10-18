"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Lock, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Logo } from "@/components/shell";
import { Button, Callout, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({
  email: z.string().min(3, "Enter your email"),
  password: z.string().min(1, "Enter your password"),
  totp: z.string().optional(),
});

function LoginForm() {
  const { signIn, me } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = React.useState<string | null>(null);
  const [needsMfa, setNeedsMfa] = React.useState(false);
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";

  React.useEffect(() => {
    if (me) router.replace(safeNext);
  }, [me, router, safeNext]);

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await signIn(v.email, v.password, v.totp);
    } catch (e) {
      if (e instanceof ApiError && e.code === "mfa_required") {
        setNeedsMfa(true);
        return;
      }
      setError(e instanceof ApiError ? e.message : "Sign-in failed.");
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <Field label="Email" error={form.formState.errors.email?.message}>
        <Input type="email" autoComplete="username" {...form.register("email")} />
      </Field>
      <Field label="Password" error={form.formState.errors.password?.message}>
        <Input type="password" autoComplete="current-password" {...form.register("password")} />
      </Field>
      {needsMfa && (
        <Field label="One-time code" hint="Enter the 6-digit code from your authenticator app.">
          <Input inputMode="numeric" autoComplete="one-time-code" {...form.register("totp")} />
        </Field>
      )}
      {error && <Callout tone="danger">{error}</Callout>}
      <Button type="submit" variant="primary" className="w-full" loading={form.formState.isSubmitting} icon={<Lock className="h-4 w-4" />}>
        Sign in
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="aegis-backdrop flex min-h-screen items-center justify-center p-4">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl border border-line/80 bg-surface/80 shadow-panel backdrop-blur lg:grid-cols-[1.1fr_1fr]">
        <div className="relative hidden flex-col justify-between border-r border-line/70 p-10 lg:flex">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_300px_at_0%_0%,rgb(var(--accent)/0.18),transparent),radial-gradient(500px_300px_at_100%_100%,rgb(var(--violet)/0.12),transparent)]" />
          <div className="relative">
            <Logo />
            <h1 className="mt-10 text-3xl font-semibold leading-tight tracking-tight">
              Evidence first.
              <br />
              <span className="bg-gradient-to-r from-accent to-cyan bg-clip-text text-transparent">Uncertainty stated.</span>
            </h1>
            <p className="mt-4 max-w-md text-sm leading-relaxed text-muted">
              AEGIS helps authorised analysts examine whether content may have been generated or altered by AI — keeping statistical
              inference, watermark verification, signed provenance and human judgement clearly apart.
            </p>
          </div>
          <ul className="relative space-y-3 text-sm text-muted">
            {[
              "A detector flag starts a review. It never establishes misconduct.",
              "Absence of a watermark or provenance record proves nothing about authorship.",
              "Every finding carries its method version, input hash and limitations.",
            ].map((t) => (
              <li key={t} className="flex gap-2.5">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> {t}
              </li>
            ))}
          </ul>
        </div>
        <div className="p-8 sm:p-10">
          <div className="lg:hidden">
            <Logo />
          </div>
          <div className="mt-6 lg:mt-0">
            <div className="label flex items-center gap-2">
              <KeyRound className="h-3.5 w-3.5" /> Authorised access
            </div>
            <h2 className="mt-2 text-xl font-semibold">Sign in to your workspace</h2>
            <p className="mt-1 text-sm text-muted">Sessions are short-lived and every action is recorded in a tamper-evident audit trail.</p>
          </div>
          <div className="mt-8">
            <React.Suspense>
              <LoginForm />
            </React.Suspense>
          </div>
          <p className="mt-8 text-xs leading-relaxed text-muted">
            Development installations can be seeded with demo accounts (<code className="hash">make seed-demo</code>). Demo credentials are
            for local evaluation only and are disabled in production.
          </p>
        </div>
      </div>
    </div>
  );
}
