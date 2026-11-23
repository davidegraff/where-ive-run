import { Decoder, Stream } from "@garmin/fitsdk";
import type { LatLng } from "../../../shared/model.ts";
import type { ParsedTrack } from "./track.ts";

const SEMI = 180 / 2 ** 31;

/** Read the GPS route and session summary from a FIT file (Garmin, Wahoo, Coros, Strava app…). */
export function parseFit(bytes: Uint8Array): ParsedTrack {
  const points: LatLng[] = [];
  const decoder = new Decoder(Stream.fromByteArray(bytes));
  // Disabling the expansions we don't need roughly halves decode time.
  const { messages } = decoder.read({
    expandSubFields: false,
    expandComponents: false,
    mergeHeartRates: false,
    includeUnknownData: false,
    decodeMemoGlobs: false,
  });
  const m = messages as Record<string, any[] | undefined>;
  for (const r of m.recordMesgs ?? []) {
    const lat = r.positionLat, lng = r.positionLong;
    if (typeof lat === "number" && typeof lng === "number" && (lat !== 0 || lng !== 0)) points.push([lat * SEMI, lng * SEMI]);
  }
  const sessions = m.sessionMesgs ?? [];
  const s = sessions[0];
  const sum = (f: string) => sessions.reduce((t, x) => t + (typeof x[f] === "number" ? x[f] : 0), 0);
  const startTime = s?.startTime ?? m.activityMesgs?.[0]?.timestamp ?? m.fileIdMesgs?.[0]?.timeCreated;
  const sport = s ? (s.subSport && !["generic", "street"].includes(s.subSport) ? `${s.subSport} ${s.sport}` : s.sport) : m.sportMesgs?.[0]?.sport;
  return {
    points,
    start: startTime instanceof Date ? startTime : undefined,
    sport: typeof sport === "string" ? sport : undefined,
    name: m.sportMesgs?.[0]?.name,
    distance_m: sum("totalDistance") || undefined,
    moving_s: sum("totalTimerTime") || undefined,
    elev_m: sum("totalAscent") || undefined,
  };
}
