"use client";

import type { Me } from "@aegis/shared-types";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { api, initialOrganization, login as apiLogin, logout as apiLogout, onSessionExpired, refreshSession, setOrganization } from "@/lib/api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  can: (perm: string) => boolean;
  signIn: (email: string, password: string, totp?: string) => Promise<void>;
  signOut: () => Promise<void>;
  switchOrganization: (id: string) => Promise<void>;
}

const Ctx = React.createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = React.useState<Me | null>(null);
  const [loading, setLoading] = React.useState(true);
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();

  const loadMe = React.useCallback(async () => {
    const m = await api<Me>("/auth/me");
    setMe(m);
    setOrganization(m.organization.id);
    return m;
  }, []);

  React.useEffect(() => {
    setOrganization(initialOrganization());
    (async () => {
      try {
        if (await refreshSession()) await loadMe();
      } catch {
        setMe(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [loadMe]);

  React.useEffect(
    () =>
      onSessionExpired(() => {
        setMe(null);
        qc.clear();
        if (pathname !== "/login") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      }),
    [qc, router, pathname],
  );

  const value: AuthState = {
    me,
    loading,
    can: (perm) => !!me?.permissions.includes(perm),
    signIn: async (email, password, totp) => {
      await apiLogin(email, password, totp);
      await loadMe();
    },
    signOut: async () => {
      await apiLogout().catch(() => undefined);
      setMe(null);
      qc.clear();
      router.replace("/login");
    },
    switchOrganization: async (id) => {
      setOrganization(id);
      qc.clear();
      await loadMe();
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
