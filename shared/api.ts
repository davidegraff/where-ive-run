// The HTTP contract between the page (web/) and the server (server/). Both sides import these types,
// so a change here is checked on both ends by `npm run typecheck`.
//
//   GET    /api/activities            → ActivitiesResponse
//   DELETE /api/activities            → 204          (deletes the user's activities and import history)
//   GET    /api/imports               → ImportRecord[]
//   POST   /api/uploads               → UploadResult  (raw file body; file name in the X-Filename header)
//   POST   /api/imports               → NDJSON stream of ImportEvent, one per line (body: ImportRequest)
//   GET    /api/cities?since=<cursor> → CityUpdate    (city names filled in since the cursor)
import type { Activity, CityTag, SourceId } from "./model.ts";

export interface ImportRecord {
  id: number;
  /** ISO time of the import. */
  at: string;
  /** Uploaded file name (or "N files"). */
  file: string;
  source: SourceId;
  label: string;
  activities: number;
}

export interface ActivitiesResponse {
  activities: Activity[];
  /** Pass as /api/cities?since= to hear about city names filled in after this response. */
  cityCursor: number;
}

export interface UploadResult { uploadId: string; name: string; size: number }

export interface ImportRequest {
  /** Upload ids from POST /api/uploads. Each zip is matched to a source on its own; loose files form one group. */
  uploads: string[];
}

export interface SourceSummary {
  file: string;
  source: SourceId;
  label: string;
  activities: number;
  withGps: number;
  warnings: number;
}

export type ImportEvent =
  | { type: "progress"; file: string; label: string; done: number; total: number }
  | { type: "warning"; message: string }
  | { type: "source-done"; summary: SourceSummary }
  /** Last line of a successful import. The page then fetches /api/activities. */
  | { type: "done"; summaries: SourceSummary[] }
  /** Last line of a failed import. */
  | { type: "error"; message: string };

export interface CityUpdate {
  tags: CityTag[];
  /** Pass back as ?since= to get only newer tags. */
  cursor: number;
  /** Start areas still waiting for a name (0 once the lookup has caught up). */
  pending: number;
}

export interface ApiError { error: string }
