// Uploads and import jobs. A file is uploaded on its own (POST /api/uploads) and written to disk;
// an import (POST /api/imports) then hands one or more uploads to a worker thread and stores what it finds.
import { randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, rm } from "node:fs/promises";
import type { IncomingMessage } from "node:http";
import { join } from "node:path";
import { Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { Worker } from "node:worker_threads";
import type { ImportEvent, SourceSummary, UploadResult } from "../shared/api.ts";
import type { WorkerInput, WorkerMessage } from "./ingest/worker.ts";
import type { Store } from "./store.ts";

interface Upload { user: string; name: string; path: string; size: number; expires: number }

/** Uploads that haven't been imported within this time are deleted. */
const UPLOAD_TTL_MS = 60 * 60_000;

export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export function createImports(store: Store, uploadDir: string, maxUploadBytes: number) {
  const uploads = new Map<string, Upload>();

  const discard = async (id: string) => {
    const u = uploads.get(id);
    uploads.delete(id);
    if (u) await rm(u.path, { force: true });
  };
  const sweep = setInterval(() => {
    const now = Date.now();
    for (const [id, u] of uploads) if (u.expires < now) void discard(id);
  }, 60_000);
  sweep.unref();

  return {
    /** Stream a request body to disk. The name is only used for display and to recognise the file type. */
    async receive(user: string, name: string, req: IncomingMessage): Promise<UploadResult> {
      name = name.split(/[\\/]/).pop()!.slice(0, 255);
      if (!name) throw new HttpError(400, "Missing file name (X-Filename header)");
      const declared = Number(req.headers["content-length"] ?? NaN);
      if (declared > maxUploadBytes) throw new HttpError(413, "File is too large");

      await mkdir(uploadDir, { recursive: true });
      const id = randomUUID();
      const path = join(uploadDir, id);
      let size = 0;
      const limit = new Transform({
        transform(chunk: Buffer, _enc, cb) {
          size += chunk.length;
          cb(size > maxUploadBytes ? new HttpError(413, "File is too large") : null, chunk);
        },
      });
      try {
        await pipeline(req, limit, createWriteStream(path));
      } catch (e) {
        await rm(path, { force: true });
        throw e;
      }
      uploads.set(id, { user, name, path, size, expires: Date.now() + UPLOAD_TTL_MS });
      return { uploadId: id, name, size };
    },

    /**
     * Run an import over the given uploads, calling emit for each public event. Activities are saved as
     * they arrive. The uploads are deleted afterwards, whatever happens. Abort the signal to stop early.
     */
    async run(user: string, ids: string[], emit: (e: ImportEvent) => void, signal: AbortSignal): Promise<SourceSummary[] | null> {
      if (!Array.isArray(ids) || !ids.length) throw new HttpError(400, "No uploads given");
      const files = ids.map(id => {
        const u = uploads.get(id);
        if (!u || u.user !== user) throw new HttpError(404, `Unknown upload ${id}`);
        return { name: u.name, path: u.path };
      });
      try {
        return await new Promise<SourceSummary[] | null>((resolve, reject) => {
          const worker = new Worker(new URL("./ingest/worker.ts", import.meta.url), { workerData: { files } satisfies WorkerInput });
          const stop = () => { void worker.terminate(); resolve(null); };
          signal.addEventListener("abort", stop, { once: true });
          worker.on("error", reject);
          worker.on("exit", () => signal.removeEventListener("abort", stop));
          worker.on("message", (m: WorkerMessage) => {
            try {
              if (m.type === "batch") store.putActivities(user, m.activities);
              else if (m.type === "done") {
                const at = new Date().toISOString();
                for (const s of m.summaries) store.addImport(user, { at, file: s.file, source: s.source, label: s.label, activities: s.activities });
                emit(m);
                resolve(m.summaries);
              } else {
                emit(m);
                if (m.type === "error") resolve(null);
              }
            } catch (e) {
              void worker.terminate();
              reject(e);
            }
          });
        });
      } finally {
        await Promise.all(ids.map(discard));
      }
    },

    close: () => clearInterval(sweep),
  };
}
