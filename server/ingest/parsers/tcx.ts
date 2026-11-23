import type { LatLng } from "../../../shared/model.ts";
import type { ParsedTrack } from "./track.ts";
import { allBlocks, attr, firstText } from "./xml.ts";
import { elevationGain } from "./gpx.ts";

export function parseTcx(xml: string): ParsedTrack {
  const points: LatLng[] = [];
  const eles: number[] = [];
  for (const tp of allBlocks(xml, "Trackpoint")) {
    const pos = firstText(tp, "Position");
    if (pos) {
      const lat = Number(firstText(pos, "LatitudeDegrees")), lng = Number(firstText(pos, "LongitudeDegrees"));
      if (Number.isFinite(lat) && Number.isFinite(lng)) points.push([lat, lng]);
    }
    const alt = firstText(tp, "AltitudeMeters");
    if (alt) eles.push(Number(alt));
  }
  const act = /<(?:[\w.-]+:)?Activity\b[^>]*>/.exec(xml)?.[0] ?? "";
  const id = firstText(xml, "Id");
  let dist = 0, time = 0;
  for (const lap of allBlocks(xml, "Lap")) {
    const head = lap.replace(/<(?:[\w.-]+:)?Track\b[\s\S]*<\/(?:[\w.-]+:)?Track>/g, "");
    dist += Number(firstText(head, "DistanceMeters") ?? 0) || 0;
    time += Number(firstText(head, "TotalTimeSeconds") ?? 0) || 0;
  }
  const start = id ? new Date(id) : undefined;
  return {
    points,
    start: start && !isNaN(+start) ? start : undefined,
    sport: attr(act, "Sport"),
    distance_m: dist || undefined,
    moving_s: time || undefined,
    elev_m: elevationGain(eles),
  };
}
