import type { Entry } from "../entries.ts";
import { stravaArchive } from "./strava-archive.ts";
import { trackFiles } from "./track-files.ts";
import type { SourceAdapter } from "./types.ts";

export type { SourceAdapter, ImportContext } from "./types.ts";

/** Tried in order; the first whose detect() matches handles the files. Most specific first. */
export const ADAPTERS: SourceAdapter[] = [stravaArchive, trackFiles];

export const detectAdapter = (entries: Entry[]) => ADAPTERS.find(a => a.detect(entries));
