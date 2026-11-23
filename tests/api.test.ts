// The server's HTTP API, end to end: upload → import (in a worker thread) → stored activities → city names.
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { ActivitiesResponse, CityUpdate, ImportEvent, ImportRecord, UploadResult } from "../shared/api.ts";
import { createApp } from "../server/app.ts";
import { createCityLookup, type Lookup } from "../server/geocode.ts";
import { openStore, type Store } from "../server/store.ts";
import { GPX, TCX, makeFit } from "./fixtures.ts";

let dir: string, base: string, store: Store, server: ReturnType<typeof createApp>, cities: ReturnType<typeof createCityLookup>;
const looked: [number, number][] = [];
const fakeLookup: Lookup = async at => { looked.push(at); return { city: "Testville", region: "TS", country: "Testland" }; };

beforeAll(async () => {
  dir = mkdtempSync(join(tmpdir(), "wir-api-"));
  store = openStore(join(dir, "app.db"));
  cities = createCityLookup(store, fakeLookup, { gapMs: 0 });
  server = createApp({ store, cities, uploadDir: join(dir, "uploads"), maxUploadBytes: 1 << 20 });
  await new Promise<void>(r => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await cities.idle();
  await new Promise(r => server.close(r));
  store.close();
  rmSync(dir, { recursive: true, force: true });
});

async function uploadFile(name: string, body: string | Uint8Array<ArrayBuffer>) {
  const r = await fetch(base + "/api/uploads", { method: "POST", body, headers: { "X-Filename": encodeURIComponent(name) } });
  return { status: r.status, body: (await r.json()) as UploadResult & { error?: string } };
}

async function runImport(uploads: string[]): Promise<ImportEvent[]> {
  const r = await fetch(base + "/api/imports", { method: "POST", body: JSON.stringify({ uploads }), headers: { "Content-Type": "application/json" } });
  expect(r.headers.get("content-type")).toMatch(/ndjson/);
  return (await r.text()).trim().split("\n").map(l => JSON.parse(l));
}

const get = async <T>(path: string) => (await (await fetch(base + path)).json()) as T;

describe("API", () => {
  it("imports uploaded files and serves the activities", async () => {
    const ids = [];
    for (const [name, body] of [["a.gpx", GPX], ["b.tcx", TCX], ["c.fit", makeFit()]] as const) {
      const u = await uploadFile(name, body as string | Uint8Array<ArrayBuffer>);
      expect(u.status).toBe(201);
      ids.push(u.body.uploadId);
    }
    const events = await runImport(ids);
    const done = events.at(-1)!;
    expect(done.type).toBe("done");
    if (done.type === "done") expect(done.summaries).toMatchObject([{ source: "track-files", activities: 3, withGps: 3 }]);
    expect(events.some(e => e.type === "progress")).toBe(true);

    const { activities } = await get<ActivitiesResponse>("/api/activities");
    expect(activities.map(a => [a.type, a.date])).toEqual([
      ["Run", "2020-05-01T10:00:00"], ["Ride", "2021-07-04T08:30:00"], ["Trail Run", "2022-03-05T07:00:00"],
    ]);
    expect(await get<ImportRecord[]>("/api/imports")).toMatchObject([{ file: "3 files", source: "track-files", activities: 3 }]);
    // uploads are deleted once imported, and can't be imported twice
    expect(readdirSync(join(dir, "uploads"))).toEqual([]);
    expect((await runImport(ids)).at(-1)).toMatchObject({ type: "error" });
  });

  it("names cities in the background and reports them since a cursor", async () => {
    await cities.idle();
    expect(looked).toHaveLength(3); // Boston, London and Paris are far apart: three lookups
    const u = await get<CityUpdate>("/api/cities?since=0");
    expect(u.tags).toHaveLength(3);
    expect(u.tags[0]).toMatchObject({ city: "Testville", region: "TS" });
    expect(u.pending).toBe(0);
    expect((await get<CityUpdate>(`/api/cities?since=${u.cursor}`)).tags).toEqual([]);
    const { activities, cityCursor } = await get<ActivitiesResponse>("/api/activities");
    expect(cityCursor).toBe(u.cursor);
    expect(activities.every(a => a.city === "Testville")).toBe(true);
  });

  it("keeps city names when the same activity is imported again", async () => {
    const u = await uploadFile("again.gpx", GPX);
    await runImport([u.body.uploadId]);
    await cities.idle();
    expect(looked).toHaveLength(3);
    const { activities } = await get<ActivitiesResponse>("/api/activities");
    expect(activities).toHaveLength(3);
    expect(activities.every(a => a.city === "Testville")).toBe(true);
  });

  it("reports unreadable files as an import error", async () => {
    const u = await uploadFile("notes.txt", "hello");
    const events = await runImport([u.body.uploadId]);
    expect(events.at(-1)).toMatchObject({ type: "error", message: expect.stringMatching(/Couldn't find any activities/) });
  });

  it("rejects uploads over the size limit", async () => {
    const u = await uploadFile("big.gpx", new Uint8Array((1 << 20) + 1));
    expect(u.status).toBe(413);
  });

  it("deletes everything", async () => {
    expect((await fetch(base + "/api/activities", { method: "DELETE" })).status).toBe(204);
    expect((await get<ActivitiesResponse>("/api/activities")).activities).toEqual([]);
    expect(await get<ImportRecord[]>("/api/imports")).toEqual([]);
  });

  it("answers unknown routes with a JSON 404", async () => {
    const r = await fetch(base + "/api/nope");
    expect(r.status).toBe(404);
    expect(await r.json()).toMatchObject({ error: expect.any(String) });
  });
});
