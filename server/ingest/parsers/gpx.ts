import type { LatLng } from "../../../shared/model.ts";
import { pathLength } from "../geo.ts";
import type { ParsedTrack } from "./track.ts";
import { attr, firstText } from "./xml.ts";

export function parseGpx(xml: string): ParsedTrack {
  const points: LatLng[] = [];
  const eles: number[] = [];
  const re = /<(?:[\w.-]+:)?trkpt\b([^>]*?)(\/>|>([\s\S]*?)<\/(?:[\w.-]+:)?trkpt>)/g;
  let start: Date | undefined, end: Date | undefined;
  for (let m; (m = re.exec(xml)); ) {
    const lat = Number(attr(m[1], "lat")), lon = Number(attr(m[1], "lon"));
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    points.push([lat, lon]);
    const body = m[3];
    if (body) {
      const t = /<(?:[\w.-]+:)?time>([^<]+)</.exec(body);
      if (t) { const d = new Date(t[1].trim()); if (!isNaN(+d)) { start ??= d; end = d; } }
      const e = /<(?:[\w.-]+:)?ele>([^<]+)</.exec(body);
      if (e) eles.push(Number(e[1]));
    }
  }
  const trk = /<(?:[\w.-]+:)?trk\b[\s\S]*?(?=<(?:[\w.-]+:)?trkseg\b)/.exec(xml)?.[0] ?? "";
  const metaTime = firstText(xml, "metadata");
  if (!start && metaTime) { const t = firstText(metaTime, "time"); if (t) start = new Date(t); }
  return {
    points,
    start,
    name: firstText(trk, "name"),
    sport: firstText(trk, "type"),
    distance_m: pathLength(points),
    moving_s: start && end ? (+end - +start) / 1000 : undefined,
    elev_m: elevationGain(eles),
  };
}

/** Sum of climbs, ignoring wiggles under 3 m (GPS altitude noise). */
export function elevationGain(eles: number[]): number {
  let gain = 0, ref = NaN;
  for (const e of eles) {
    if (!Number.isFinite(e)) continue;
    if (isNaN(ref)) { ref = e; continue; }
    if (e > ref + 3) { gain += e - ref; ref = e; }
    else if (e < ref) ref = e;
  }
  return gain;
}
