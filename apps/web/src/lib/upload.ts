import type { EvidenceItem } from "@aegis/shared-types";

import { api } from "@/lib/api";

const CHUNKED_THRESHOLD = 8 * 1024 * 1024;

/** Uploads evidence; files above 8 MB use the resumable chunked protocol with real byte progress. */
export async function uploadEvidence(
  caseId: string,
  file: File,
  role: "primary" | "process_evidence",
  onProgress?: (sent: number, total: number) => void,
  description?: string,
): Promise<EvidenceItem> {
  if (file.size <= CHUNKED_THRESHOLD) {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("role", role);
    if (description) form.append("description", description);
    const item = await api<EvidenceItem>(`/investigations/${caseId}/evidence`, { form });
    onProgress?.(file.size, file.size);
    return item;
  }
  const init = await api<{ upload_id: string; chunk_size: number; received: number }>(`/investigations/${caseId}/uploads`, {
    json: { filename: file.name, total_size: file.size, role },
  });
  let offset = init.received;
  while (offset < file.size) {
    const chunk = file.slice(offset, offset + init.chunk_size);
    const r = await api<{ received: number }>(`/uploads/${init.upload_id}?offset=${offset}`, { method: "PUT", body: chunk, headers: { "Content-Type": "application/octet-stream" } });
    offset = r.received;
    onProgress?.(offset, file.size);
  }
  return api<EvidenceItem>(`/uploads/${init.upload_id}/complete`, { method: "POST" });
}

export async function sha256Hex(file: File): Promise<string | null> {
  if (!globalThis.crypto?.subtle || file.size > 256 * 1024 * 1024) return null;
  const buf = await file.arrayBuffer();
  const h = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export const ACCEPT =
  ".txt,.pdf,.docx,.png,.jpg,.jpeg,.webp,.wav,.mp3,.m4a,.mp4,text/plain,application/pdf,image/png,image/jpeg,image/webp,audio/wav,audio/mpeg,audio/mp4,video/mp4";

export function defaultProfile(modality: string): string {
  return { text: "text_triage", document: "text_triage", image: "image_investigation", audio: "synthetic_speech", video: "deepfake_video" }[modality] ?? "comprehensive";
}
