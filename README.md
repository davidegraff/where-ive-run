# Where I've Run

An interactive heatmap of every activity you've recorded. Upload your Strava archive (or any GPX / TCX / FIT files) and the server turns it into a map you can explore. You don't need a Strava subscription or API key.

- **Routes and glow:** every GPS route is drawn on the map. When zoomed out, places glow in proportion to how many activities passed through them.
- **Timeline:** drag the slider, or press ▶, to watch your activities build up from the first one to today.
- **Activity filter:** toggle chips for each activity type (Run, Ride, Hike, …). Hover over a chip and click **only** to show just that type.
- **Cities:** each activity is grouped by the city it started in. Click a city to fly there.
- **Map styles:** Dark, Light, Roads, Terrain, Satellite and Hybrid, picked from the preview box in the bottom-left corner.
- **Options:** seven route colors, and km or miles (click the distance stat).

All map backgrounds are free services that need no keys: Esri, OpenFreeMap, OpenTopoMap and OpenStreetMap.

## Supported data

| Source | How |
| --- | --- |
| **Strava archive** | strava.com → **Settings → My Account → Download or Delete Your Account → Get Started → Request Your Archive**. Strava emails you a zip within a few hours. Drop the zip on the page as it is. |
| **GPX / TCX / FIT files** | From any app or device. Drop the files, or a zip of them. |

Planned: Garmin Connect archive, a linked Strava account, Apple Health.

## Running it

Requires Node 24 or newer (the server runs its TypeScript directly, with no build step).

```bash
npm install
```

```bash
npm run dev
```

Then open http://127.0.0.1:5173. This starts two processes: the API server on port 8787, which restarts when `server/` or `shared/` changes, and Vite's dev server for the page, which forwards `/api` requests to the API server. `npm run dev:server` and `npm run dev:web` start just one of them.

For production, build the page once, then run the server. It serves the API and the built page from one port:

```bash
npm run build
```

```bash
HOST=0.0.0.0 PORT=8787 npm start
```

Settings are environment variables, listed at the top of [server/main.ts](server/main.ts): `DATA_DIR` (the database and uploads, default `./data`), `MAX_UPLOAD_MB`, `GEOCODE=off`, `NOMINATIM_USER_AGENT`, and others.

```bash
npm test
```

To check the importer against a real archive and the old Python importer's output:

```bash
STRAVA_ARCHIVE=~/Downloads/export_12345.zip LEGACY_JSON=data/runs.json npx vitest run tests/archive-compare.test.ts
```

## Privacy

- Uploaded files are written to `DATA_DIR/uploads/`, read by the server, and deleted as soon as the import finishes (or after an hour if it never runs).
- The activities found in them, including every GPS route, are stored in `DATA_DIR/app.db` (SQLite). **Delete all** in the sidebar removes them. `data/` is git-ignored because of this. Keep it out of the repo.
- To name cities, the server asks OpenStreetMap's [Nominatim](https://nominatim.org) about each area where an activity started, with the location rounded to about 1 km. Nominatim's usage policy allows one request per second for each application, so the whole server shares a single queue. The first import of a few hundred places takes a few minutes. Answers are cached and shared between users, since they hold only place names.
- **There are no accounts yet.** Everyone who can reach the server sees the same data, so only run it on your own machine or behind something that already restricts access. All requests go through `currentUser()` in [server/auth.ts](server/auth.ts), and every database row is scoped to the id it returns. Adding sign-in means replacing that one function.

## How it fits together

```
 web/ (the page)                         server/ (the API)
 ────────────────                        ─────────────────────────────────────────────────────────────
 drop files ── POST /api/uploads ──────▶ uploads/ on disk
            ── POST /api/imports ──────▶ worker thread: adapter (Strava archive / track files / …)
            ◀─ progress (NDJSON stream) ─┘                └─▶ Activity[] ─▶ SQLite
 map        ◀─ GET /api/activities ───── SQLite
 city list  ◀─ GET /api/cities (poll) ── background city lookup (Nominatim, 1 req/s)
```

The code is split into three parts, each with its own `tsconfig.json`, so the page can't reach into server code and the server can't use browser APIs:

- **`shared/`** is the contract between the two: the `Activity` shape ([shared/model.ts](shared/model.ts)), every API route and its request/response types ([shared/api.ts](shared/api.ts)), and the polyline encoding.
- **`server/`** ingests and normalizes data. Every source is converted into the same `Activity` shape. To add a source, write a `SourceAdapter` ([server/ingest/adapters/types.ts](server/ingest/adapters/types.ts)) with a `detect()` that recognises its files and a `read()` that yields activities, then add it to `ADAPTERS` in [server/ingest/adapters/index.ts](server/ingest/adapters/index.ts).
- **`web/`** is the page. It only talks to the server through [web/api.ts](web/api.ts).

| Path | What it does |
| --- | --- |
| `shared/model.ts`, `shared/api.ts` | The activity shape and the HTTP API's types |
| `shared/polyline.ts` | Google polyline encode (server) / decode (page) |
| `server/main.ts` | Entry point and settings |
| `server/app.ts` | HTTP routes; serves the built page from `dist/` in production |
| `server/auth.ts` | `currentUser()`: the one place to add sign-in |
| `server/imports.ts` | Receives uploads, runs import jobs in a worker thread, saves the results |
| `server/store.ts` | SQLite storage (Node's built-in `node:sqlite`) |
| `server/geocode.ts` | Groups start points and names their cities, one shared queue |
| `server/ingest/pipeline.ts`, `entries.ts`, `worker.ts` | Unzips (on demand, so multi-GB archives are fine) and picks an adapter for each upload |
| `server/ingest/adapters/` | One file per data source |
| `server/ingest/parsers/` | GPX, TCX, FIT (Garmin's FIT SDK) and CSV readers |
| `web/index.html`, `web/styles.css` | Page layout and styles |
| `web/main.ts` | Startup, file drop / picker, upload and import progress, "Your data" panel |
| `web/api.ts` | The page's API client |
| `web/view/heatmap.ts` | Map, timeline, filters, cities list (Leaflet, leaflet.heat; MapLibre loads only for the Roads style) |
| `tests/` | Parser, pipeline and API tests, plus the optional real-archive comparison |
| `tools/dev.ts` | Starts the API server and Vite together for `npm run dev` |
| `scripts/*.py` | The original command-line importers, kept for now as a reference (see below) |

### The old command-line version

Before the webapp, a Python script turned the archive into `data/runs.js` for a static `heatmap.html`. The scripts are still in `scripts/` (`uv sync`, then `uv run python -I scripts/import_strava_export.py export.zip`), but nothing reads their output any more.
