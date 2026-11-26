// Generated from server/models.py by `npm run gen:api` (python -m server.typescript). Don't edit by hand.

export type SourceId = "strava-archive" | "track-files";

export type LatLng = [number, number];

/** The one activity shape every data source is converted into. */
export interface Activity {
  /** Primary key: "{source}:{source_id}". Re-importing the same source overwrites instead of duplicating. */
  key: string;
  source: "strava-archive" | "track-files";
  /** The id the source uses (Strava activity id, start time of a GPX file, ...). */
  source_id: string;
  name: string;
  /** Start time in UTC as "YYYY-MM-DDTHH:MM:SS" (no zone suffix, like the Strava export). */
  date: string;
  /** Strava-style type name: "Run", "Ride", "Hike", ... */
  type: string;
  distance_m: number;
  moving_s: number;
  elev_m: number;
  start: [number, number] | null;
  /** Google encoded polyline of the thinned route ("" when there is no GPS). */
  polyline: string;
  /** Link back to the activity on the source's website, if it has one. */
  url: string | null;
  /** Filled in after import by the background city lookup. */
  city: string | null;
  region: string | null;
}

export interface ActivitiesResponse {
  activities: Activity[];
  /** Pass as /api/cities?since= to hear about city names filled in after this response. */
  city_cursor: number;
}

export interface CityTag {
  key: string;
  city: string;
  region: string;
}

export interface CityUpdate {
  tags: CityTag[];
  /** Pass back as ?since= to get only newer tags. */
  cursor: number;
  /** Activities still waiting for a city name (0 once the lookup has caught up or stopped). */
  pending: number;
  /** Why the lookup stopped early (e.g. no connection to OpenStreetMap); it retries after the next import. */
  error: string | null;
}

export interface ImportRecord {
  id: number;
  /** ISO time of the import. */
  at: string;
  /** Uploaded file name (or "N files"). */
  file: string;
  source: "strava-archive" | "track-files";
  label: string;
  activities: number;
}

export interface UploadResult {
  upload_id: string;
  name: string;
  size: number;
}

export interface ImportRequest {
  /** Upload ids from POST /api/uploads. Each zip is matched to a source on its own; loose files form one group. */
  uploads: string[];
}

export interface SourceSummary {
  file: string;
  source: "strava-archive" | "track-files";
  label: string;
  activities: number;
  with_gps: number;
  warnings: number;
}

export type ImportEvent = ProgressEvent | WarningEvent | SourceDoneEvent | DoneEvent | ErrorEvent;

/** The body of every 4xx / 5xx response. */
export interface ApiError {
  error: string;
}

/** Last line of a successful import. The page then fetches /api/activities. */
export interface DoneEvent {
  type: "done";
  summaries: SourceSummary[];
}

/** Last line of a failed import. */
export interface ErrorEvent {
  type: "error";
  message: string;
}

export interface ProgressEvent {
  type: "progress";
  file: string;
  label: string;
  done: number;
  total: number;
}

export interface SourceDoneEvent {
  type: "source-done";
  summary: SourceSummary;
}

/** A non-fatal problem, e.g. one unreadable file. */
export interface WarningEvent {
  type: "warning";
  message: string;
}
