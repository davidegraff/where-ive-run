import type { ImportEvent, SourceSummary } from "../../shared/api.ts";
import type { Activity } from "../../shared/model.ts";
import { ADAPTERS, detectAdapter, type SourceAdapter } from "./adapters/index.ts";
import { blobEntry, isZip, zipEntries, type Entry } from "./entries.ts";

/** One uploaded file. `blob` is read lazily (e.g. fs.openAsBlob), so a multi-GB zip is never loaded whole. */
export interface InputFile { name: string; blob: Blob }

/** What the pipeline reports: the public ImportEvents, plus batches of activities for the server to store. */
export type PipelineEvent =
  | Extract<ImportEvent, { type: "progress" | "warning" | "source-done" }>
  | { type: "batch"; activities: Activity[] };

const BATCH = 100;

/**
 * Turn whatever the user uploaded into Activity objects. Each zip is matched to an adapter on its own
 * (a Strava archive and a Garmin archive can be dropped together); loose files are handled as one group.
 * Throws if nothing recognisable was found.
 */
export async function runImport(files: InputFile[], emit: (e: PipelineEvent) => void): Promise<SourceSummary[]> {
  const jobs: { name: string; entries: Entry[]; close?: () => Promise<void> }[] = [];
  const loose: Entry[] = [];
  for (const f of files) {
    if (isZip(f.name)) {
      const z = await zipEntries(f.blob);
      jobs.push({ name: f.name, entries: z.entries, close: z.close });
    } else loose.push(blobEntry(f.name, f.blob));
  }
  if (loose.length) jobs.push({ name: loose.length === 1 ? loose[0].path : `${loose.length} files`, entries: loose });

  const summaries: SourceSummary[] = [];
  const unknown: string[] = [];
  for (const job of jobs) {
    const adapter = detectAdapter(job.entries);
    try {
      if (!adapter) { unknown.push(job.name); continue; }
      summaries.push(await runAdapter(adapter, job.name, job.entries, emit));
    } finally {
      await job.close?.();
    }
  }
  for (const name of unknown) emit({ type: "warning", message: `${name}: not a format we can read yet` });
  if (!summaries.length) {
    throw new Error(
      `Couldn't find any activities in ${unknown.join(", ")}. Supported: ${ADAPTERS.map(a => a.label).join(", ")}.`,
    );
  }
  return summaries;
}

async function runAdapter(adapter: SourceAdapter, file: string, entries: Entry[], emit: (e: PipelineEvent) => void) {
  const summary: SourceSummary = { file, source: adapter.id, label: adapter.label, activities: 0, withGps: 0, warnings: 0 };
  let batch: Activity[] = [];
  let lastProgress = 0;
  const ctx = {
    progress(done: number, total: number) {
      const now = Date.now();
      if (done === total || now - lastProgress > 100) {
        lastProgress = now;
        emit({ type: "progress", file, label: adapter.label, done, total });
      }
    },
    warn(message: string) {
      summary.warnings++;
      emit({ type: "warning", message });
    },
  };
  for await (const a of adapter.read(entries, ctx)) {
    summary.activities++;
    if (a.polyline) summary.withGps++;
    batch.push(a);
    if (batch.length >= BATCH) { emit({ type: "batch", activities: batch }); batch = []; }
  }
  if (batch.length) emit({ type: "batch", activities: batch });
  emit({ type: "source-done", summary });
  return summary;
}
