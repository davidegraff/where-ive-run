// Runs one import in a worker thread, so parsing a large archive never blocks the HTTP server.
// The parent sends the uploaded files' paths; the worker streams back PipelineEvents, then done / error.
import { openAsBlob } from "node:fs";
import { parentPort, workerData } from "node:worker_threads";
import type { SourceSummary } from "../../shared/api.ts";
import { runImport, type PipelineEvent } from "./pipeline.ts";

export interface WorkerInput { files: { name: string; path: string }[] }
export type WorkerMessage = PipelineEvent | { type: "done"; summaries: SourceSummary[] } | { type: "error"; message: string };

const post = (m: WorkerMessage) => parentPort!.postMessage(m);

try {
  const { files } = workerData as WorkerInput;
  const inputs = await Promise.all(files.map(async f => ({ name: f.name, blob: await openAsBlob(f.path) })));
  post({ type: "done", summaries: await runImport(inputs, post) });
} catch (err) {
  post({ type: "error", message: (err as Error).message || String(err) });
}
