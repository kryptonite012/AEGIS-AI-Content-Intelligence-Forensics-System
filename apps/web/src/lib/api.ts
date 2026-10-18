// Thin API client. The access token lives in memory only; the refresh token is an httpOnly,
// SameSite=Strict cookie scoped to /api/v1/auth. Every request goes through the same-origin
// Next.js rewrite, so no API origin or secret is exposed to the browser.

export const API_BASE = process.env.NEXT_PUBLIC_AEGIS_API_BASE || "/api/v1";

let accessToken: string | null = null;
let organizationId: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public correlationId?: string | null,
  ) {
    super(message);
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setOrganization(id: string | null) {
  organizationId = id;
  try {
    if (id) sessionStorage.setItem("aegis.org", id);
    else sessionStorage.removeItem("aegis.org");
  } catch {
    /* storage unavailable */
  }
}

export function initialOrganization(): string | null {
  try {
    return sessionStorage.getItem("aegis.org");
  } catch {
    return null;
  }
}

export function onSessionExpired(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  if (accessToken) h.set("Authorization", `Bearer ${accessToken}`);
  if (organizationId) h.set("X-AEGIS-Organization", organizationId);
  h.set("X-Requested-With", "aegis-web");
  return h;
}

export async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-Requested-With": "aegis-web" },
        });
        if (!r.ok) return false;
        const body = await r.json();
        accessToken = body.access_token;
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

async function toError(r: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await r.json();
  } catch {
    /* non-JSON */
  }
  const e = body?.error;
  return new ApiError(r.status, e?.code ?? "http_error", e?.message ?? r.statusText, e?.details, e?.correlation_id);
}

export interface RequestOptions {
  method?: string;
  json?: unknown;
  form?: FormData;
  body?: BodyInit;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

export async function request(path: string, opts: RequestOptions = {}, retry = true): Promise<Response> {
  const h = headers(opts.headers);
  let body: BodyInit | undefined = opts.body;
  if (opts.json !== undefined) {
    h.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  const r = await fetch(`${API_BASE}${path}`, {
    method: opts.method ?? (body ? "POST" : "GET"),
    headers: h,
    body,
    credentials: "same-origin",
    signal: opts.signal,
  });
  if (r.status === 401 && retry && !path.startsWith("/auth/login")) {
    if (await refreshSession()) return request(path, opts, false);
    accessToken = null;
    listeners.forEach((fn) => fn());
  }
  if (!r.ok) throw await toError(r);
  return r;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const r = await request(path, opts);
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

export async function login(email: string, password: string, totp?: string) {
  const body = await api<{ access_token: string }>("/auth/login", { json: { email, password, totp: totp || undefined } });
  accessToken = body.access_token;
}

export async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } finally {
    accessToken = null;
  }
}

/** Authenticated binary fetch → object URL (for images and downloads). */
export async function blobUrl(path: string): Promise<string> {
  const r = await request(path);
  return URL.createObjectURL(await r.blob());
}

export async function download(path: string, fallbackName: string) {
  const r = await request(path);
  const disp = r.headers.get("Content-Disposition") || "";
  const m = /filename="([^"]+)"/.exec(disp);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = m?.[1] || fallbackName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** Server-sent events over fetch (EventSource cannot send the Authorization header). */
export async function streamEvents(path: string, onEvent: (data: any) => void, signal: AbortSignal) {
  const r = await request(path, { signal });
  const reader = r.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = chunk
        .split("\n")
        .filter((l) => l.startsWith("data: "))
        .map((l) => l.slice(6))
        .join("\n");
      if (data) onEvent(JSON.parse(data));
    }
  }
}
