/** The one activity shape every data source is converted into. */
export type LatLng = [number, number];

export type SourceId = "strava-archive" | "track-files";

export interface Activity {
  /** Primary key: `${source}:${sourceId}`. Re-importing the same source overwrites instead of duplicating. */
  key: string;
  source: SourceId;
  /** The id the source uses (Strava activity id, file name, …). */
  sourceId: string;
  name: string;
  /** Start time in UTC as "YYYY-MM-DDTHH:MM:SS" (no zone suffix, like the Strava export). */
  date: string;
  /** Strava-style type name: "Run", "Ride", "Hike", … */
  type: string;
  distance_m: number;
  moving_s: number;
  elev_m: number;
  start: LatLng | null;
  /** Google encoded polyline of the thinned route ("" when there is no GPS). */
  polyline: string;
  /** Link back to the activity on the source's website, if it has one. */
  url?: string;
  /** Filled in after import by the city lookup. */
  city?: string;
  region?: string;
}

export const activityKey = (source: SourceId, sourceId: string) => `${source}:${sourceId}`;

/** City names come from the server's background lookup and are sent to the page separately. */
export type CityTag = Pick<Activity, "key" | "city" | "region">;
