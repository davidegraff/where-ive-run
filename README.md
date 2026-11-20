# Where I've Run

An interactive heatmap of every activity in your Strava account, built from Strava's free bulk export. No Strava subscription or API key is needed.

- **Routes and glow:** every GPS route is drawn on the map. When zoomed out, places glow in proportion to how many activities passed through them.
- **Timeline:** drag the slider, or press ▶, to watch your activities build up from the first one to today.
- **Activity filter:** toggle chips for each activity type (Run, Ride, Hike, …). Hover over a chip and click **only** to show just that type.
- **Cities:** each activity is grouped by the city it started in. Click a city to fly there.
- **Map styles:** Dark, Light, Roads, Terrain, Satellite and Hybrid, picked from the preview box in the bottom-left corner.
- **Options:** seven route colors, and km or miles (click the distance stat).

All map backgrounds are free services that need no keys: Esri, OpenFreeMap, OpenTopoMap and OpenStreetMap.

## Setup

1. **Get your data.** On strava.com go to **Settings → My Account → Download or Delete Your Account → Get Started → Request Your Archive**. Strava emails you a zip, usually within a few hours.

2. **Install the dependencies** with [uv](https://docs.astral.sh/uv/) (the one dependency, `fitdecode`, reads `.fit` files):

   ```bash
   uv sync
   ```

3. **Import the export.** This reads the zip in place, writes `data/runs.js`, then names the city for each start area using OpenStreetMap's Nominatim. The city lookup runs at about one request per second, with results cached for later imports.

   ```bash
   uv run python -I scripts/import_strava_export.py ~/Downloads/export_12345.zip
   ```

4. **Open the map.** Serve the folder locally, then visit http://localhost:8765/heatmap.html:

   ```bash
   uv run python -m http.server 8765 --bind 127.0.0.1
   ```

To update the map later, request a new archive and run step 3 again.

## Privacy

`data/` is git-ignored on purpose. It holds every GPS route and start location, which reveal where you live and the routes you run regularly. Keep it out of the repo, especially a public one.

## Files

| Path | What it does |
| --- | --- |
| `pyproject.toml`, `uv.lock` | Python dependencies, managed with uv |
| `heatmap.html` | The whole app (Leaflet, leaflet.heat, MapLibre for the Roads style) |
| `scripts/import_strava_export.py` | Strava export zip → `data/runs.js` (GPX, TCX and FIT supported) |
| `scripts/add_cities.py` | Tags each activity with its starting city (called by the importer) |
| `scripts/fetch_strava_runs.py` | Alternative importer using the Strava API. Strava now limits API apps to subscribers on some accounts |
