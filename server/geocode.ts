// Names the city each activity started in, using OpenStreetMap's Nominatim.
// Start points within ~3 km are grouped and looked up once; answers are cached in the places table.
// Nominatim's usage policy allows at most 1 request per second *per application*, so there is a single
// queue for the whole server, shared by all users. A first import of a few hundred places takes a few
// minutes; it runs in the background and the page picks up names as they arrive (GET /api/cities).
import type { LatLng } from "../shared/model.ts";
import type { Place, Store, Untagged } from "./store.ts";

const RADIUS_KM = 3;
const GAP_MS = 1100;

const km = (a: LatLng, b: LatLng) => {
  const dy = (a[0] - b[0]) * 111.32;
  const dx = (a[1] - b[1]) * 111.32 * Math.cos((((a[0] + b[0]) / 2) * Math.PI) / 180);
  return Math.hypot(dx, dy);
};

/** Greedy clustering on a grid index. */
export function cluster<T extends { start: LatLng }>(items: T[]): { center: LatLng; members: T[] }[] {
  const groups: { center: LatLng; members: T[] }[] = [];
  const cells = new Map<string, number[]>();
  const cell = RADIUS_KM / 111.32;
  for (const a of items) {
    const p = a.start;
    const cx = Math.floor(p[0] / cell), cy = Math.floor(p[1] / cell);
    let best = -1, bestD = RADIUS_KM;
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        for (const g of cells.get(`${cx + dx},${cy + dy}`) ?? []) {
          const d = km(groups[g].center, p);
          if (d < bestD) { best = g; bestD = d; }
        }
    if (best < 0) {
      groups.push({ center: p, members: [a] });
      const k = `${cx},${cy}`;
      cells.set(k, [...(cells.get(k) ?? []), groups.length - 1]);
    } else groups[best].members.push(a);
  }
  return groups;
}

export type Lookup = (at: LatLng) => Promise<Place>;

/** Nominatim reverse geocoding. The location is rounded to ~1 km: enough to name the city (zoom 10). */
export function nominatim(userAgent: string): Lookup {
  return async ([lat, lng]) => {
    const q = new URLSearchParams({ format: "jsonv2", lat: lat.toFixed(2), lon: lng.toFixed(2), zoom: "10", "accept-language": "en" });
    const r = await fetch("https://nominatim.openstreetmap.org/reverse?" + q, { headers: { "User-Agent": userAgent } });
    if (!r.ok) throw new Error(`Nominatim ${r.status}`);
    const a = (((await r.json()) as { address?: Record<string, string> }).address ?? {});
    const city = a.city || a.town || a.village || a.municipality || a.hamlet || a.suburb || a.county || a.state || "Unknown";
    let region = a.country ?? "";
    if (a.country_code === "us") {
      const iso = a["ISO3166-2-lvl4"] ?? "";
      const st = iso.startsWith("US-") ? iso.split("-").pop() : a.state;
      region = st ? `${st}, USA` : "USA";
    }
    return { city, region, country: a.country ?? "" };
  };
}

const sleep = (ms: number) => new Promise(res => setTimeout(res, ms));

/**
 * The background city lookup. Call schedule() after an import (and once at startup); it works through
 * every user's untagged activities, then idles. Lookups that fail three times are left untagged and
 * retried the next time schedule() is called.
 */
export function createCityLookup(store: Store, lookup: Lookup | null, opts: { gapMs?: number; retryMs?: number } = {}) {
  const gapMs = opts.gapMs ?? GAP_MS, retryMs = opts.retryMs ?? 5000;
  let running: Promise<void> | null = null;
  let again = false;

  async function tagUser(user: string, todo: Untagged[]) {
    for (const g of cluster(todo)) {
      const key = `${g.center[0].toFixed(3)},${g.center[1].toFixed(3)}`;
      let place = store.place(key);
      if (!place) {
        for (let attempt = 0; attempt < 3 && !place; attempt++) {
          try { place = await lookup!(g.center); }
          catch (e) { console.warn(`City lookup failed (${(e as Error).message}), retrying`); await sleep(retryMs); }
        }
        if (place) store.putPlace(key, place);
        await sleep(gapMs);
      }
      if (place) store.tagCities(user, g.members.map(m => m.key), place);
    }
  }

  async function loop() {
    do {
      again = false;
      for (const user of store.usersWithUntagged()) await tagUser(user, store.untagged(user));
    } while (again);
  }

  return {
    schedule() {
      if (!lookup) return;
      if (running) { again = true; return; }
      running = loop()
        .catch(e => console.error("City lookup stopped:", e))
        .finally(() => { running = null; });
    },
    /** True while lookups are queued or in flight. */
    get active() { return running !== null; },
    /** Resolves when the queue is empty (for tests and shutdown). */
    idle: () => running ?? Promise.resolve(),
  };
}

export type CityLookup = ReturnType<typeof createCityLookup>;
