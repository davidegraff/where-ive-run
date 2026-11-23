import type { LatLng } from "../../../shared/model.ts";

/** What a single GPX / TCX / FIT file tells us. Only `points` is guaranteed. */
export interface ParsedTrack {
  points: LatLng[];
  start?: Date;
  /** Source-specific sport name, mapped to a Strava-style type by `normalizeType`. */
  sport?: string;
  name?: string;
  distance_m?: number;
  moving_s?: number;
  elev_m?: number;
}

/** Map sport names used by GPX / TCX / FIT / Garmin to Strava-style activity types. */
export function normalizeType(sport: string | undefined): string {
  if (!sport) return "Workout";
  const s = sport.toLowerCase().replace(/[\s_-]+/g, "");
  const table: [RegExp, string][] = [
    [/trailrun/, "Trail Run"],
    [/virtualrun|treadmill/, "Virtual Run"],
    [/run/, "Run"],
    [/mountainbik|mtb/, "Mountain Bike Ride"],
    [/gravel/, "Gravel Ride"],
    [/virtualride|indoorcycl|virtualactivity/, "Virtual Ride"],
    [/ebik/, "E-Bike Ride"],
    [/bik|cycl|ride/, "Ride"],
    [/hik/, "Hike"],
    [/walk/, "Walk"],
    [/swim/, "Swim"],
    [/backcountry|alpineski|downhillski|crosscountryski|nordicski|ski/, "Ski"],
    [/snowboard/, "Snowboard"],
    [/kayak/, "Kayaking"],
    [/canoe/, "Canoeing"],
    [/row/, "Rowing"],
    [/paddle|sup/, "Stand Up Paddling"],
    [/inlineskat|rollerskat/, "Inline Skate"],
    [/iceskat|skat/, "Ice Skate"],
    [/surf/, "Surfing"],
    [/climb/, "Rock Climb"],
    [/golf/, "Golf"],
    [/yoga/, "Yoga"],
  ];
  for (const [re, t] of table) if (re.test(s)) return t;
  if (s === "generic" || s === "other" || s === "all") return "Workout";
  return sport.charAt(0).toUpperCase() + sport.slice(1);
}
