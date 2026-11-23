// The page's only way to reach its data: thin wrappers over the server API (types in shared/api.ts).
import type { ActivitiesResponse, ApiError, CityUpdate, ImportEvent, ImportRecord, SourceSummary, UploadResult } from "../shared/api.ts";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(await errorText(r));
  return (r.status === 204 ? undefined : await r.json()) as T;
}

async function errorText(r: Response) {
  try { return ((await r.json()) as ApiError).error; } catch { return `Server error ${r.status}`; }
}

export const getActivities = () => call<ActivitiesResponse>("/api/activities");
export const getImports = () => call<ImportRecord[]>("/api/imports");
export const deleteActivities = () => call<void>("/api/activities", { method: "DELETE" });
export const getCities = (since: number) => call<CityUpdate>(`/api/cities?since=${since}`);

/** Upload one file. Uses XHR rather than fetch because fetch can't report upload progress. */
export function upload(file: File, progress: (sent: number, total: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/uploads");
    x.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    x.responseType = "json";
    x.upload.onprogress = e => progress(e.loaded, e.total || file.size);
    x.onload = () => (x.status < 300 ? resolve(x.response) : reject(new Error(x.response?.error ?? `Upload failed (${x.status})`)));
    x.onerror = () => reject(new Error("Upload failed: couldn't reach the server"));
    x.send(file);
  });
}

/** Ask the server to import some uploads, reporting its progress events as they stream in. */
export async function runImport(uploads: string[], onEvent: (e: ImportEvent) => void): Promise<SourceSummary[]> {
  const r = await fetch("/api/imports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uploads }),
  });
  if (!r.ok || !r.body) throw new Error(await errorText(r));
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const e = JSON.parse(buf.slice(0, nl)) as ImportEvent;
      buf = buf.slice(nl + 1);
      if (e.type === "done" || e.type === "error") {
        void reader.cancel();
        if (e.type === "error") throw new Error(e.message);
        return e.summaries;
      }
      onEvent(e);
    }
  }
  throw new Error("The server stopped before the import finished");
}
