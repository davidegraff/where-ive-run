import { activityKey, type Activity } from "../../../shared/model.ts";
import { encodePolyline, isoNoZone, thin } from "../geo.ts";
import { isTrackFile, normalizeType, parseTrackFile } from "../parsers/index.ts";
import type { SourceAdapter } from "./types.ts";

/** Loose GPX / TCX / FIT files (or a zip of them) from any app or device. */
export const trackFiles: SourceAdapter = {
  id: "track-files",
  label: "GPX / TCX / FIT files",

  detect: entries => entries.some(e => isTrackFile(e.path)),

  async *read(entries, ctx) {
    const files = entries.filter(e => isTrackFile(e.path));
    for (let i = 0; i < files.length; i++) {
      const e = files[i];
      const base = e.path.split("/").pop()!;
      try {
        const t = await parseTrackFile(e.path, await e.read());
        const pts = thin(t.points);
        if (!t.start && pts.length < 2) {
          ctx.warn(`${base}: no time or GPS data, skipped`);
          continue;
        }
        // Keyed by start time, so the same activity exported as both GPX and FIT is stored once.
        const sourceId = t.start ? isoNoZone(t.start) : base;
        const type = normalizeType(t.sport);
        const a: Activity = {
          key: activityKey("track-files", sourceId),
          source: "track-files",
          sourceId,
          name: t.name || defaultName(type, t.start),
          date: t.start ? isoNoZone(t.start) : "",
          type,
          distance_m: t.distance_m ?? 0,
          moving_s: t.moving_s ?? 0,
          elev_m: t.elev_m ?? 0,
          start: pts[0] ?? null,
          polyline: pts.length > 1 ? encodePolyline(pts) : "",
        };
        yield a;
      } catch (err) {
        ctx.warn(`Could not read ${base}: ${(err as Error).message}`);
      } finally {
        ctx.progress(i + 1, files.length);
      }
    }
  },
};

function defaultName(type: string, start?: Date) {
  if (!start) return type;
  const h = start.getHours();
  return `${h < 12 ? "Morning" : h < 17 ? "Afternoon" : h < 21 ? "Evening" : "Night"} ${type}`;
}
