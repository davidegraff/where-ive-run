// SQLite storage (Node's built-in node:sqlite, so there's no native module to install).
// Every activity and import belongs to a user id; see auth.ts for where that id comes from.
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { ImportRecord } from "../shared/api.ts";
import type { Activity, CityTag, LatLng, SourceId } from "../shared/model.ts";

export interface Place { city: string; region: string; country: string }

/** An activity with a start point and no city yet, as the city lookup needs it. */
export interface Untagged { key: string; start: LatLng }

const SCHEMA = `
CREATE TABLE IF NOT EXISTS activities (
  user_id    TEXT NOT NULL,
  key        TEXT NOT NULL,
  source     TEXT NOT NULL,
  source_id  TEXT NOT NULL,
  name       TEXT NOT NULL,
  date       TEXT NOT NULL,
  type       TEXT NOT NULL,
  distance_m REAL NOT NULL,
  moving_s   REAL NOT NULL,
  elev_m     REAL NOT NULL,
  start_lat  REAL,
  start_lng  REAL,
  polyline   TEXT NOT NULL,
  url        TEXT,
  city       TEXT,
  region     TEXT,
  -- Increases each time a city is filled in, so the page can ask for "tags since N".
  city_seq   INTEGER,
  PRIMARY KEY (user_id, key)
);
CREATE INDEX IF NOT EXISTS activities_city_seq ON activities (user_id, city_seq);
CREATE TABLE IF NOT EXISTS imports (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    TEXT NOT NULL,
  at         TEXT NOT NULL,
  file       TEXT NOT NULL,
  source     TEXT NOT NULL,
  label      TEXT NOT NULL,
  activities INTEGER NOT NULL
);
-- Reverse-geocode answers keyed by "lat,lng" (3 decimals). Shared by all users: it holds only place names.
CREATE TABLE IF NOT EXISTS places (
  key     TEXT PRIMARY KEY,
  city    TEXT NOT NULL,
  region  TEXT NOT NULL,
  country TEXT NOT NULL
);
`;

// Re-importing an activity keeps its city if the start point hasn't moved, so re-imports don't re-geocode.
const SAME_START = `((activities.start_lat IS NULL AND excluded.start_lat IS NULL)
  OR (abs(activities.start_lat - excluded.start_lat) < 1e-3 AND abs(activities.start_lng - excluded.start_lng) < 1e-3))`;

type Row = Record<string, string | number | null>;

const toActivity = (r: Row): Activity => ({
  key: r.key as string,
  source: r.source as SourceId,
  sourceId: r.source_id as string,
  name: r.name as string,
  date: r.date as string,
  type: r.type as string,
  distance_m: r.distance_m as number,
  moving_s: r.moving_s as number,
  elev_m: r.elev_m as number,
  start: r.start_lat === null ? null : [r.start_lat as number, r.start_lng as number],
  polyline: r.polyline as string,
  ...(r.url ? { url: r.url as string } : {}),
  ...(r.city ? { city: r.city as string, region: (r.region as string) ?? "" } : {}),
});

export type Store = ReturnType<typeof openStore>;

export function openStore(file: string) {
  if (file !== ":memory:") mkdirSync(dirname(file), { recursive: true });
  const db = new DatabaseSync(file);
  db.exec("PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL;");
  db.exec(SCHEMA);

  const q = {
    all: db.prepare("SELECT * FROM activities WHERE user_id = ? ORDER BY date, key"),
    upsert: db.prepare(`
      INSERT INTO activities (user_id, key, source, source_id, name, date, type, distance_m, moving_s, elev_m,
                              start_lat, start_lng, polyline, url)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT (user_id, key) DO UPDATE SET
        source = excluded.source, source_id = excluded.source_id, name = excluded.name, date = excluded.date,
        type = excluded.type, distance_m = excluded.distance_m, moving_s = excluded.moving_s, elev_m = excluded.elev_m,
        start_lat = excluded.start_lat, start_lng = excluded.start_lng, polyline = excluded.polyline, url = excluded.url,
        city     = CASE WHEN ${SAME_START} THEN activities.city     ELSE NULL END,
        region   = CASE WHEN ${SAME_START} THEN activities.region   ELSE NULL END,
        city_seq = CASE WHEN ${SAME_START} THEN activities.city_seq ELSE NULL END`),
    deleteActivities: db.prepare("DELETE FROM activities WHERE user_id = ?"),
    deleteImports: db.prepare("DELETE FROM imports WHERE user_id = ?"),
    addImport: db.prepare("INSERT INTO imports (user_id, at, file, source, label, activities) VALUES (?, ?, ?, ?, ?, ?)"),
    imports: db.prepare("SELECT id, at, file, source, label, activities FROM imports WHERE user_id = ? ORDER BY id"),
    usersUntagged: db.prepare("SELECT DISTINCT user_id FROM activities WHERE city IS NULL AND start_lat IS NOT NULL"),
    // Date order makes the clusters (and so the cache keys) the same from one run to the next.
    untagged: db.prepare("SELECT key, start_lat, start_lng FROM activities WHERE user_id = ? AND city IS NULL AND start_lat IS NOT NULL ORDER BY date, key"),
    countUntagged: db.prepare("SELECT count(*) AS n FROM activities WHERE user_id = ? AND city IS NULL AND start_lat IS NOT NULL"),
    maxSeq: db.prepare("SELECT coalesce(max(city_seq), 0) AS n FROM activities"),
    tag: db.prepare("UPDATE activities SET city = ?, region = ?, city_seq = ? WHERE user_id = ? AND key = ?"),
    tagsSince: db.prepare("SELECT key, city, region, city_seq FROM activities WHERE user_id = ? AND city_seq > ? ORDER BY city_seq"),
    place: db.prepare("SELECT city, region, country FROM places WHERE key = ?"),
    putPlace: db.prepare("INSERT OR REPLACE INTO places (key, city, region, country) VALUES (?, ?, ?, ?)"),
  };

  let seq = Number((q.maxSeq.get() as Row).n);

  const tx = <T>(fn: () => T): T => {
    db.exec("BEGIN");
    try { const r = fn(); db.exec("COMMIT"); return r; }
    catch (e) { db.exec("ROLLBACK"); throw e; }
  };

  return {
    activities: (user: string): Activity[] => (q.all.all(user) as Row[]).map(toActivity),

    putActivities(user: string, list: Activity[]) {
      tx(() => {
        for (const a of list) {
          q.upsert.run(user, a.key, a.source, a.sourceId, a.name, a.date, a.type, a.distance_m, a.moving_s, a.elev_m,
            a.start?.[0] ?? null, a.start?.[1] ?? null, a.polyline, a.url ?? null);
        }
      });
    },

    /** Delete the user's activities and import history. The shared place-name cache is kept. */
    clear(user: string) {
      tx(() => { q.deleteActivities.run(user); q.deleteImports.run(user); });
    },

    addImport(user: string, r: Omit<ImportRecord, "id">) {
      q.addImport.run(user, r.at, r.file, r.source, r.label, r.activities);
    },
    imports: (user: string): ImportRecord[] => q.imports.all(user) as unknown as ImportRecord[],

    // ---------- city lookup ----------
    usersWithUntagged: () => (q.usersUntagged.all() as Row[]).map(r => r.user_id as string),
    untagged: (user: string): Untagged[] =>
      (q.untagged.all(user) as Row[]).map(r => ({ key: r.key as string, start: [r.start_lat as number, r.start_lng as number] })),
    countUntagged: (user: string) => Number((q.countUntagged.get(user) as Row).n),

    tagCities(user: string, keys: string[], place: Place) {
      tx(() => { for (const k of keys) q.tag.run(place.city, place.region, ++seq, user, k); });
    },
    /** The latest city tag's sequence number (read it before reading activities). */
    cityCursor: () => seq,
    tagsSince(user: string, cursor: number): { tags: CityTag[]; cursor: number } {
      const rows = q.tagsSince.all(user, cursor) as Row[];
      return {
        tags: rows.map(r => ({ key: r.key as string, city: r.city as string, region: (r.region as string) ?? "" })),
        cursor: rows.length ? Number(rows.at(-1)!.city_seq) : Math.max(cursor, 0),
      };
    },

    place: (key: string) => q.place.get(key) as Place | undefined,
    putPlace: (key: string, p: Place) => { q.putPlace.run(key, p.city, p.region, p.country); },

    close: () => db.close(),
  };
}
