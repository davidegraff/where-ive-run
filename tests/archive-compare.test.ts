// Checks the server importer against the old Python importer's output on a real Strava archive.
// Skipped unless both are available:
//   STRAVA_ARCHIVE=~/Downloads/export_123.zip LEGACY_JSON=data/runs.json npx vitest run tests/archive-compare.test.ts
import { openAsBlob } from "node:fs";
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Activity } from "../shared/model.ts";
import { decodePolyline } from "../shared/polyline.ts";
import { runImport } from "../server/ingest/pipeline.ts";

const archive = process.env.STRAVA_ARCHIVE?.replace(/^~/, process.env.HOME ?? "~");
const legacy = process.env.LEGACY_JSON;
const enabled = !!archive && !!legacy && existsSync(archive) && existsSync(legacy);

describe.skipIf(!enabled)("Strava archive import matches the Python importer", () => {
  it("produces the same activities", async () => {
    const blob = await openAsBlob(archive!);
    const file = { name: archive!.split("/").pop()!, blob };
    const got: Activity[] = [];
    const warnings: string[] = [];
    const t0 = performance.now();
    const summaries = await runImport([file], e => {
      if (e.type === "batch") got.push(...e.activities);
      if (e.type === "warning") warnings.push(e.message);
    });
    const secs = (performance.now() - t0) / 1000;
    console.log(`imported ${got.length} activities in ${secs.toFixed(1)} s`, summaries, warnings.slice(0, 5));

    const want: any[] = JSON.parse(readFileSync(legacy!, "utf8"));
    expect(got.length).toBe(want.length);
    const byId = new Map(got.map(a => [a.sourceId, a]));
    let polyDiff = 0;
    for (const w of want) {
      const g = byId.get(String(w.id))!;
      expect(g, `activity ${w.id}`).toBeTruthy();
      expect(g.date).toBe(w.date);
      expect(g.type).toBe(w.type);
      expect(g.name).toBe(w.name);
      expect(g.distance_m).toBeCloseTo(w.distance_m, 3);
      expect(g.moving_s).toBeCloseTo(w.moving_s, 3);
      expect(g.elev_m).toBeCloseTo(w.elev_m, 3);
      expect(!!g.polyline).toBe(!!w.polyline);
      if (w.start) {
        expect(g.start![0]).toBeCloseTo(w.start[0], 5);
        expect(g.start![1]).toBeCloseTo(w.start[1], 5);
      }
      if (g.polyline !== w.polyline) {
        // Python's round() rounds halves to even, Math.round rounds them up: allow 1e-5° (about 1 m).
        polyDiff++;
        const a = decodePolyline(g.polyline), b = decodePolyline(w.polyline);
        expect(a.length).toBe(b.length);
        for (let i = 0; i < a.length; i++) {
          expect(Math.abs(a[i][0] - b[i][0])).toBeLessThan(1.5e-5);
          expect(Math.abs(a[i][1] - b[i][1])).toBeLessThan(1.5e-5);
        }
      }
    }
    console.log(`${polyDiff} of ${want.length} polylines differ by rounding only`);
  }, 600_000);
});
