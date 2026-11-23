import { describe, expect, it } from "vitest";
import { decodePolyline, encodePolyline } from "../shared/polyline.ts";
import type { Activity } from "../shared/model.ts";
import { thin } from "../server/ingest/geo.ts";
import { parseCsv } from "../server/ingest/parsers/csv.ts";
import { parseGpx } from "../server/ingest/parsers/gpx.ts";
import { parseTcx } from "../server/ingest/parsers/tcx.ts";
import { parseFit } from "../server/ingest/parsers/fit.ts";
import { normalizeType } from "../server/ingest/parsers/track.ts";
import { parseStravaDate } from "../server/ingest/adapters/strava-archive.ts";
import { runImport, type InputFile } from "../server/ingest/pipeline.ts";
import { GPX, TCX, makeFit } from "./fixtures.ts";

describe("geo", () => {
  it("round-trips polylines", () => {
    const pts: [number, number][] = [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]];
    expect(encodePolyline(pts)).toBe("_p~iF~ps|U_ulLnnqC_mqNvxq`@"); // Google's documented example
    expect(decodePolyline(encodePolyline(pts))).toEqual(pts);
  });
  it("thins close points but keeps the last one", () => {
    const pts: [number, number][] = [[0, 0], [0.00001, 0], [0.00002, 0], [0.001, 0], [0.00101, 0]];
    expect(thin(pts)).toEqual([[0, 0], [0.001, 0], [0.00101, 0]]);
  });
});

describe("parsers", () => {
  it("reads GPX", () => {
    const t = parseGpx(GPX);
    expect(t.points).toHaveLength(3);
    expect(t.points[0]).toEqual([42.36, -71.06]);
    expect(t.name).toBe("Lunch & Run");
    expect(t.sport).toBe("running");
    expect(t.start?.toISOString()).toBe("2020-05-01T10:00:00.000Z");
    expect(t.moving_s).toBe(120);
    expect(t.distance_m).toBeGreaterThan(220);
    expect(t.distance_m).toBeLessThan(225);
    expect(t.elev_m).toBe(5);
  });

  it("reads TCX, skipping trackpoints without a position", () => {
    const t = parseTcx(TCX);
    expect(t.points).toEqual([[51.5, -0.12], [51.51, -0.12]]);
    expect(t.sport).toBe("Biking");
    expect(t.distance_m).toBe(5000);
    expect(t.moving_s).toBe(600);
    expect(t.elev_m).toBe(10);
    expect(t.start?.toISOString()).toBe("2021-07-04T08:30:00.000Z");
  });

  it("reads FIT", () => {
    const t = parseFit(makeFit());
    expect(t.points).toHaveLength(3);
    expect(t.points[0][0]).toBeCloseTo(48.85, 6);
    expect(t.points[0][1]).toBeCloseTo(2.35, 6);
    expect(t.start?.toISOString()).toBe("2022-03-05T07:00:00.000Z");
    expect(normalizeType(t.sport)).toBe("Trail Run");
    expect(t.distance_m).toBeCloseTo(222.5);
    expect(t.moving_s).toBe(120);
    expect(t.elev_m).toBe(7);
  });

  it("parses quoted CSV fields with commas, quotes and newlines", () => {
    expect(parseCsv('﻿a,b,c\r\n1,"x, ""y""\nz",3\n')).toEqual([["a", "b", "c"], ["1", 'x, "y"\nz', "3"]]);
  });

  it("parses Strava's date formats", () => {
    expect(parseStravaDate("Dec 6, 2018, 12:09:18 PM")).toBe("2018-12-06T12:09:18");
    expect(parseStravaDate("Jan 1, 2020, 12:05:00 AM")).toBe("2020-01-01T00:05:00");
    expect(parseStravaDate("Jul 4, 2021, 3:07:09 PM")).toBe("2021-07-04T15:07:09");
    expect(parseStravaDate("6 Dec 2018, 13:09:18")).toBe("2018-12-06T13:09:18");
    expect(parseStravaDate("2018-12-06 12:09:18")).toBe("2018-12-06T12:09:18");
  });

  it("maps sport names to Strava-style types", () => {
    expect(normalizeType("running")).toBe("Run");
    expect(normalizeType("Biking")).toBe("Ride");
    expect(normalizeType("cycling")).toBe("Ride");
    expect(normalizeType("hiking")).toBe("Hike");
    expect(normalizeType(undefined)).toBe("Workout");
  });
});

describe("import pipeline", () => {
  const file = (name: string, body: string | Uint8Array<ArrayBuffer>): InputFile => ({ name, blob: new Blob([body]) });
  const collect = async (files: InputFile[]) => {
    const got: Activity[] = [];
    const summaries = await runImport(files, e => { if (e.type === "batch") got.push(...e.activities); });
    return { got, summaries };
  };

  it("imports loose GPX / TCX / FIT files", async () => {
    const { got, summaries } = await collect([
      file("a.gpx", GPX), file("b.tcx", TCX), file("c.fit", makeFit() as Uint8Array<ArrayBuffer>),
    ]);
    expect(summaries).toHaveLength(1);
    expect(summaries[0].source).toBe("track-files");
    expect(got.map(a => [a.type, a.date])).toEqual([
      ["Run", "2020-05-01T10:00:00"], ["Ride", "2021-07-04T08:30:00"], ["Trail Run", "2022-03-05T07:00:00"],
    ]);
    expect(got.every(a => a.polyline && a.start)).toBe(true);
  });

  it("gives a clear error for unsupported files", async () => {
    await expect(collect([file("notes.txt", "hello")])).rejects.toThrow(/Couldn't find any activities/);
  });
});
