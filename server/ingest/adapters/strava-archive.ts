import { activityKey, type Activity, type LatLng } from "../../../shared/model.ts";
import type { Entry } from "../entries.ts";
import { encodePolyline, thin } from "../geo.ts";
import { parseCsv } from "../parsers/csv.ts";
import { isTrackFile, parseTrackFile } from "../parsers/index.ts";
import { textOf } from "../parsers/xml.ts";
import type { SourceAdapter } from "./types.ts";

const CSV_RE = /(^|\/)activities\.csv$/;

/**
 * Strava's bulk export ("Download or Delete Your Account → Request Your Archive").
 * activities.csv has one row per activity; its Filename column points at the GPX / TCX / FIT route.
 */
export const stravaArchive: SourceAdapter = {
  id: "strava-archive",
  label: "Strava archive",

  detect: entries => entries.some(e => CSV_RE.test(e.path)),

  async *read(entries, ctx) {
    const csvEntry = entries.find(e => CSV_RE.test(e.path))!;
    const prefix = csvEntry.path.slice(0, -"activities.csv".length);
    const byPath = new Map<string, Entry>(entries.map(e => [e.path, e]));

    const [header, ...rows] = parseCsv(textOf(await csvEntry.read()));
    const col = (name: string, last = false) => {
      const idx = header.flatMap((h, i) => (h.trim() === name ? [i] : []));
      return idx.length ? (last ? idx[idx.length - 1] : idx[0]) : -1;
    };
    const c = {
      id: col("Activity ID"), date: col("Activity Date"), name: col("Activity Name"), type: col("Activity Type"),
      file: col("Filename"),
      distM: col("Distance", true), // the later "Distance" column is in metres…
      distKm: col("Distance"),      // …the first one is in the account's display unit
      moving: col("Moving Time"), elapsed: col("Elapsed Time"), elev: col("Elevation Gain"),
    };
    if (c.id < 0 || c.type < 0) throw new Error("activities.csv is missing the Activity ID / Activity Type columns");

    const valid = rows.filter(r => r[c.type]);
    for (let i = 0; i < valid.length; i++) {
      const r = valid[i];
      const get = (k: number) => (k >= 0 && k < r.length ? r[k] : "");
      let dist = num(get(c.distM));
      if (c.distM === c.distKm) dist *= 1000;

      let pts: LatLng[] = [];
      const fname = get(c.file);
      const entry = fname ? byPath.get(prefix + fname) : undefined;
      // Some rows point at .json files (e.g. manual entries with a drawn route); those carry no GPS.
      if (entry && isTrackFile(entry.path)) {
        try {
          pts = thin((await parseTrackFile(entry.path, await entry.read())).points);
        } catch (err) {
          ctx.warn(`Could not read ${fname}: ${(err as Error).message}`);
        }
      }
      const id = get(c.id);
      const a: Activity = {
        key: activityKey("strava-archive", id),
        source: "strava-archive",
        sourceId: id,
        name: get(c.name),
        date: parseStravaDate(get(c.date)),
        type: get(c.type),
        distance_m: dist,
        moving_s: num(get(c.moving)) || num(get(c.elapsed)),
        elev_m: num(get(c.elev)),
        start: pts.length ? pts[0] : null,
        polyline: pts.length > 1 ? encodePolyline(pts) : "",
        url: `https://www.strava.com/activities/${id}`,
      };
      yield a;
      ctx.progress(i + 1, valid.length);
    }
  },
};

function num(v: string): number {
  const n = Number(String(v).replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const pad = (n: number | string) => String(n).padStart(2, "0");

/** Strava writes dates in UTC as "Dec 6, 2018, 12:09:18 PM", "6 Dec 2018, 12:09:18" or "2018-12-06 12:09:18". */
export function parseStravaDate(s: string): string {
  const t = s.replace(/[  ]/g, " ").trim();
  let m = /^([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}):(\d{2}) ?([AP]M)$/i.exec(t);
  if (m) {
    let h = Number(m[4]) % 12;
    if (m[7].toUpperCase() === "PM") h += 12;
    return `${m[3]}-${pad(MONTHS.indexOf(m[1].toLowerCase()) + 1)}-${pad(m[2])}T${pad(h)}:${m[5]}:${m[6]}`;
  }
  m = /^(\d{1,2}) ([A-Za-z]{3})[a-z]*\.? (\d{4}),? (\d{1,2}):(\d{2}):(\d{2})$/.exec(t);
  if (m) return `${m[3]}-${pad(MONTHS.indexOf(m[2].toLowerCase()) + 1)}-${pad(m[1])}T${pad(m[4])}:${m[5]}:${m[6]}`;
  m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(t);
  if (m) return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}`;
  return t;
}
