import type { Activity, SourceId } from "../../../shared/model.ts";
import type { Entry } from "../entries.ts";

export interface ImportContext {
  /** Report progress through this source (done of total units). */
  progress(done: number, total: number): void;
  /** A non-fatal problem, e.g. one unreadable file. */
  warn(message: string): void;
}

/**
 * A data source. To support a new export format (Garmin, Apple Health, …), write one of these and
 * add it to ADAPTERS in ./index.ts. Linked accounts (Strava API) will produce Activity objects too,
 * but from the network instead of from entries.
 */
export interface SourceAdapter {
  id: SourceId;
  /** Shown in the UI, e.g. "Strava archive". */
  label: string;
  /** True if these entries (the contents of one dropped zip, or the loose files) are this source's format. */
  detect(entries: Entry[]): boolean;
  read(entries: Entry[], ctx: ImportContext): AsyncIterable<Activity>;
}
