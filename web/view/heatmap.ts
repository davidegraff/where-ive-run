// The map, timeline, filters and city list. Ported from the original single-file heatmap.html;
// the difference is that data arrives through setActivities() and can change while the page is open.
import L from "./leaflet.ts";
import type { Activity, CityTag, LatLng } from "../../shared/model.ts";
import { decodePolyline } from "../../shared/polyline.ts";

type Run = Activity & { pts: LatLng[]; t: number; _line?: L.Polyline | null };
type City = { city: string; region: string; idx: number[] };

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const DAY = 86_400_000;
const isRunType = (t: string) => /run/i.test(t);

// ---------- settings ----------
const COLORS: Record<string, { line: string; hi: string; grad: Record<number, string> }> = {
  orange: { line: "#ff6a2b", hi: "#ffd166", grad: { 0.2: "#5b1a0b", 0.45: "#c1370f", 0.7: "#ff6a2b", 1: "#fff1c1" } },
  blue:   { line: "#3da5ff", hi: "#d4f1ff", grad: { 0.2: "#0b1d4a", 0.45: "#1f5fc1", 0.7: "#3da5ff", 1: "#e6f7ff" } },
  green:  { line: "#2fe08a", hi: "#e0ffe9", grad: { 0.2: "#06331d", 0.45: "#139a55", 0.7: "#2fe08a", 1: "#eaffef" } },
  purple: { line: "#a77bff", hi: "#f1e6ff", grad: { 0.2: "#22104a", 0.45: "#6b3fd1", 0.7: "#a77bff", 1: "#f4ecff" } },
  pink:   { line: "#ff4fa3", hi: "#ffe3f1", grad: { 0.2: "#4a0b2a", 0.45: "#c41e6e", 0.7: "#ff4fa3", 1: "#fff0f7" } },
  red:    { line: "#ff3b3b", hi: "#ffd9c7", grad: { 0.2: "#4a0b0b", 0.45: "#b81d1d", 0.7: "#ff3b3b", 1: "#fff0e6" } },
  white:  { line: "#dfe8f2", hi: "#ffffff", grad: { 0.2: "#2a3340", 0.45: "#7b8ba0", 0.7: "#dfe8f2", 1: "#ffffff" } },
};
const pref = {
  get: (k: string, d = "") => localStorage.getItem("hm_" + k) ?? d,
  set: (k: string, v: string) => localStorage.setItem("hm_" + k, v),
};

// ---------- map styles (all free, no API keys) ----------
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const tile = (path: string) => ESRI + path + "/MapServer/tile/{z}/{y}/{x}";
const ESRI_ATTR = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";
interface Style {
  label: string; bg: string; base: [string | null, number];
  overlays?: [string, number, number][]; url?: string; vector?: string; thumb?: string; attr?: string; imagery?: boolean;
}
const STYLES: Record<string, Style> = {
  dark:      { label: "Dark",      bg: "#0b0d10", base: ["Canvas/World_Dark_Gray_Base", 16], overlays: [["Canvas/World_Dark_Gray_Reference", 16, 0.8]] },
  light:     { label: "Light",     bg: "#e9e9e6", base: ["Canvas/World_Light_Gray_Base", 16], overlays: [["Canvas/World_Light_Gray_Reference", 16, 0.9]] },
  // OpenFreeMap's "Liberty" vector style (OpenMapTiles data, drawn by MapLibre, which is loaded only when picked)
  roads:     { label: "Roads",     bg: "#f8f4f0", vector: "https://tiles.openfreemap.org/styles/liberty",
               attr: '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/" target="_blank">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>',
               thumb: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", base: [null, 19] },
  terrain:   { label: "Terrain",   bg: "#e8e4d8", url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", base: [null, 17],
               attr: 'Map data &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>, SRTM | Style &copy; <a href="https://opentopomap.org" target="_blank">OpenTopoMap</a> (CC-BY-SA)' },
  satellite: { label: "Satellite", bg: "#000",    base: ["World_Imagery", 19],
               attr: "Imagery &copy; Esri, Maxar, Earthstar Geographics", imagery: true },
  hybrid:    { label: "Hybrid",    bg: "#000",    base: ["World_Imagery", 19],
               overlays: [["Reference/World_Transportation", 19, 0.9], ["Reference/World_Boundaries_and_Places", 19, 1]],
               attr: "Imagery &copy; Esri, Maxar, Earthstar Geographics", imagery: true },
};

// ---------- formatting ----------
const KM_PER_MI = 1.609344;
const fmtDate = (t: number) => new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
const esc = (s: unknown) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const TYPE_ICONS: Record<string, string> = { run: "🏃", ride: "🚴", walk: "🚶", hike: "🥾", swim: "🏊", ski: "⛷️", snowboard: "🏂", kayak: "🛶",
  canoe: "🛶", row: "🚣", yoga: "🧘", workout: "💪", weight: "🏋️", golf: "⛳", skate: "⛸️", surf: "🏄", climb: "🧗" };
const typeIcon = (t: string) => { const k = Object.keys(TYPE_ICONS).find(k => t.toLowerCase().includes(k)); return k ? TYPE_ICONS[k] : "•"; };
const SOURCE_NAMES: Record<string, string> = { "strava-archive": "Strava" };

export interface Heatmap {
  setActivities(list: Activity[], opts?: { fit?: boolean }): void;
  /** Activities whose city/region changed (matched by key). */
  updateCities(list: CityTag[]): void;
}

export function createHeatmap(): Heatmap {
  // ALL = every activity; RUNS = those whose type is checked (everything below works on RUNS)
  let ALL: Run[] = [];
  const byKey = new Map<string, Run>();
  const hiddenTypes = new Set<string>(JSON.parse(pref.get("hiddenTypes", "[]")));
  let RUNS: Run[] = [], cumDist = [0], cumTime = [0], CITIES: City[] = [];
  let color = COLORS[pref.get("color")] ? pref.get("color") : "orange";
  let unit = pref.get("unit", "km");

  const onlyRuns = () => RUNS.length > 0 && RUNS.every(r => isRunType(r.type));
  const noun = (n: number) => (onlyRuns() ? (n === 1 ? "run" : "runs") : n === 1 ? "activity" : "activities");
  const dist = (m: number) => (unit === "mi" ? m / 1000 / KM_PER_MI : m / 1000);

  // Types with no GPS routes at all (weight training, yoga, …) draw nothing on the map, so they start
  // switched off and don't pad the totals. Only types never seen before get this default, so turning
  // one back on sticks across reloads and re-imports.
  const seenTypes = new Set<string>(JSON.parse(pref.get("seenTypes", "[]")));
  function applyTypeDefaults() {
    const gps = new Map<string, boolean>();
    for (const r of ALL) gps.set(r.type, gps.get(r.type) || r.pts.length > 1);
    let changed = false;
    for (const [type, has] of gps) {
      if (seenTypes.has(type)) continue;
      seenTypes.add(type); changed = true;
      if (!has) hiddenTypes.add(type);
    }
    if (changed) { pref.set("seenTypes", JSON.stringify([...seenTypes])); pref.set("hiddenTypes", JSON.stringify([...hiddenTypes])); }
  }
  function rebuildRuns() {
    RUNS = ALL.filter(r => !hiddenTypes.has(r.type));
    // prefix sums so the timeline can update stats instantly
    cumDist = [0]; cumTime = [0];
    for (const r of RUNS) { cumDist.push(cumDist.at(-1)! + r.distance_m); cumTime.push(cumTime.at(-1)! + r.moving_s); }
    rebuildCities();
  }
  function rebuildCities() {
    const cityMap = new Map<string, City>();
    RUNS.forEach((r, i) => {
      if (!r.start) return;
      const key = (r.city || "") + "|" + (r.region || "");
      if (!cityMap.has(key)) cityMap.set(key, { city: r.city || "Finding city…", region: r.region || "", idx: [] });
      cityMap.get(key)!.idx.push(i); // idx ascending by date
    });
    CITIES = [...cityMap.values()];
  }

  // ---------- map ----------
  const map = L.map("map", { preferCanvas: true, worldCopyJump: true }).setView([20, 0], 2);
  if (import.meta.env.DEV) (globalThis as any).__map = map; // for poking at in the dev console
  map.createPane("labels");
  map.getPane("labels")!.style.zIndex = "650";
  map.getPane("labels")!.style.pointerEvents = "none";
  let baseLayers: L.Layer[] = [];
  let mapStyle = STYLES[pref.get("style")] ? pref.get("style") : "dark";
  let styleSeq = 0;
  async function applyStyle(name: string) {
    const seq = ++styleSeq;
    mapStyle = name; pref.set("style", name);
    const s = STYLES[name];
    let base: L.Layer;
    if (s.vector) {
      const [{ maplibreGL }] = await Promise.all([
        import("@maplibre/maplibre-gl-leaflet"), import("maplibre-gl"), import("maplibre-gl/dist/maplibre-gl.css"),
      ]);
      if (seq !== styleSeq) return; // another style was picked while MapLibre loaded
      base = maplibreGL({ style: s.vector, attribution: s.attr, interactive: false } as any);
    } else {
      base = L.tileLayer(s.url || tile(s.base[0]!), { attribution: s.attr || ESRI_ATTR, maxNativeZoom: s.base[1], maxZoom: 19, subdomains: "abc" });
    }
    baseLayers.forEach(l => map.removeLayer(l));
    baseLayers = [base];
    for (const o of s.overlays || []) baseLayers.push(L.tileLayer(tile(o[0]), { pane: "labels", maxNativeZoom: o[1], maxZoom: 19, opacity: o[2] }));
    baseLayers.forEach(l => l.addTo(map));
    $("map").style.background = s.bg;
    pref.set(s.imagery ? "lastImagery" : "lastMapStyle", name);
    refreshLayersBox();
  }
  const canvas = L.canvas({ padding: 0.5 });
  const lineLayer = L.layerGroup().addTo(map);
  // maxZoom: 0 stops leaflet.heat from rescaling intensity by zoom; we do our own per-zoom counting
  const heat: any = L.heatLayer([], { radius: 14, blur: 16, maxZoom: 0, max: 1, minOpacity: 0.3, gradient: COLORS[color].grad } as any);
  // leaflet.heat can run a queued redraw after the layer was removed, or while the map has zero size
  // (e.g. a hidden window); both throw. Skip those; the next real redraw draws normally.
  {
    const redraw = heat._redraw;
    heat._redraw = function (this: any) {
      this._frame = null;
      if (!this._map || !this._heat) return;
      const s = this._map.getSize();
      if (!s.x || !s.y) return;
      return redraw.call(this);
    };
    // the public redraw() (called by setLatLngs/setOptions) reads this._map, which is null while
    // the layer is off the map (zoomed in, glow off); the data is kept and drawn on the next add
    const pubRedraw = heat.redraw;
    heat.redraw = function (this: any) { return this._map ? pubRedraw.call(this) : this; };
  }

  function pace(r: Run) {
    if (!r.distance_m || !r.moving_s) return "";
    const s = r.moving_s / dist(r.distance_m);
    return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")} /${unit}`;
  }
  const popup = (r: Run) =>
    `<b>${esc(r.name || r.type)}</b><br>${esc(r.type)} · ${fmtDate(r.t)}${r.city ? " · " + esc(r.city) : ""}<br>` +
    `${dist(r.distance_m).toFixed(2)} ${unit}` + (isRunType(r.type) || /walk|hike/i.test(r.type) ? ` · ${pace(r)}` : "") +
    (r.url ? `<br><a href="${esc(r.url)}" target="_blank" rel="noopener" style="color:#8ab4f8">Open in ${esc(SOURCE_NAMES[r.source] ?? "source")}</a>` : "");

  // ---------- route lines (created lazily and cached on each activity, added/removed as the timeline moves) ----------
  function lineFor(i: number) {
    const r = RUNS[i];
    if (r._line !== undefined) return r._line;
    if (r.pts.length < 2) return (r._line = null);
    const c = COLORS[color];
    const pl = L.polyline(r.pts, { renderer: canvas, color: c.line, weight: 2, opacity: 0.45 });
    pl.bindPopup(() => popup(r));
    pl.on("mouseover", () => pl.setStyle({ color: COLORS[color].hi, weight: 4, opacity: 1 }));
    pl.on("mouseout", () => pl.setStyle({ color: COLORS[color].line, weight: 2, opacity: 0.45 }));
    return (r._line = pl);
  }
  let shown = 0; // RUNS [0, shown) are on the map
  function showCount(n: number) {
    while (shown < n) { const l = lineFor(shown++); if (l) lineLayer.addLayer(l); }
    while (shown > n) { const l = RUNS[--shown]._line; if (l) lineLayer.removeLayer(l); }
  }
  function hideAllLines() {
    for (let i = 0; i < shown; i++) { const l = RUNS[i]._line; if (l) lineLayer.removeLayer(l); }
    shown = 0;
  }

  // ---------- timeline (spans all activities, so it doesn't jump when filters change) ----------
  const tl = $<HTMLInputElement>("tl");
  let t0 = 0, t1 = 1;
  function rebuildTimeline() {
    t0 = ALL.length ? Math.floor(ALL[0].t / DAY) : 0;
    t1 = ALL.length ? Math.ceil(ALL.at(-1)!.t / DAY) : 1;
    tl.min = "0"; tl.max = String(Math.max(1, t1 - t0)); tl.value = tl.max;
    const ticks = $("ticks");
    ticks.innerHTML = "";
    if (!ALL.length) return;
    const y0 = new Date(ALL[0].t).getFullYear(), y1 = new Date(ALL.at(-1)!.t).getFullYear();
    const step = y1 - y0 > 6 ? 2 : 1;
    for (let y = y0 + 1; y <= y1; y += step) {
      const d = Math.floor(new Date(y, 0, 1).getTime() / DAY) - t0;
      const s = document.createElement("span");
      s.style.left = (100 * d) / (t1 - t0) + "%";
      s.textContent = "’" + String(y).slice(2);
      ticks.append(s);
    }
  }
  function countUpTo(day: number) { // runs with date <= day (binary search)
    const limit = (t0 + day + 1) * DAY;
    let lo = 0, hi = RUNS.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (RUNS[m].t < limit) lo = m + 1; else hi = m; }
    return lo;
  }

  // Glow = number of runs through each area. Each run counts once per grid cell (cell = glow radius
  // in screen pixels at the current zoom), so brightness is proportional to run count, not route length.
  const CELL_PX = 14;
  let heatZoom: number | null = null, runCells: number[][] = [], cellCount = new Map<number, number>(), heatShown = 0, heatMax = 1;
  const cellCenter = new Map<number, LatLng>();
  function mercCell(lat: number, lng: number, z: number) {
    const s = (256 * Math.pow(2, z)) / CELL_PX;
    const x = Math.floor(((lng + 180) / 360) * s);
    const sin = Math.sin((lat * Math.PI) / 180);
    const y = Math.floor((0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s);
    return x * 1048576 + y;
  }
  function cellLatLng(key: number, z: number): LatLng {
    const s = (256 * Math.pow(2, z)) / CELL_PX;
    const x = Math.floor(key / 1048576), y = key % 1048576;
    const lng = ((x + 0.5) / s) * 360 - 180;
    const n = Math.PI - (2 * Math.PI * (y + 0.5)) / s;
    return [(180 / Math.PI) * Math.atan(Math.sinh(n)), lng];
  }
  function rebuildHeatCells() {
    heatZoom = Math.min(map.getZoom(), 10);
    const all = new Map<number, number>();
    runCells = RUNS.map(r => {
      const set = new Set<number>();
      for (const p of r.pts.length ? r.pts : r.start ? [r.start] : []) set.add(mercCell(p[0], p[1], heatZoom!));
      for (const k of set) all.set(k, (all.get(k) || 0) + 1);
      return [...set];
    });
    // scale against the all-time busiest cell so the glow builds up as the timeline plays
    heatMax = 1;
    for (const v of all.values()) if (v > heatMax) heatMax = v;
    cellCount = new Map(); heatShown = 0; cellCenter.clear();
  }
  let heatTimer: ReturnType<typeof setTimeout> | null = null;
  function updateHeat(n: number, now?: boolean) {
    if (heatZoom === null) rebuildHeatCells();
    while (heatShown < n) for (const k of runCells[heatShown++]) cellCount.set(k, (cellCount.get(k) || 0) + 1);
    while (heatShown > n) for (const k of runCells[--heatShown]) { const v = cellCount.get(k)! - 1; v ? cellCount.set(k, v) : cellCount.delete(k); }
    const draw = () => {
      heatTimer = null;
      const pts: [number, number, number][] = [];
      for (const [k, v] of cellCount) {
        let c = cellCenter.get(k);
        if (!c) cellCenter.set(k, (c = cellLatLng(k, heatZoom!)));
        pts.push([c[0], c[1], v]);
      }
      if (heat.options.max !== heatMax) heat.setOptions({ max: heatMax });
      heat.setLatLngs(pts);
    };
    if (now) { if (heatTimer) clearTimeout(heatTimer); draw(); }
    else if (!heatTimer) heatTimer = setTimeout(draw, 150);
  }
  map.on("zoomend", () => {
    if (Math.min(map.getZoom(), 10) !== heatZoom) { rebuildHeatCells(); updateHeat(countUpTo(+tl.value), true); }
  });

  let listTimer: ReturnType<typeof setTimeout> | null = null;
  function update(opts: { now?: boolean } = {}) {
    const n = countUpTo(+tl.value);
    showCount(n);
    updateHeat(n, opts.now);
    $("tlDate").textContent = +tl.value >= +tl.max ? "All time" : "through " + fmtDate((t0 + +tl.value) * DAY);
    $("sRuns").textContent = n.toLocaleString();
    $("sRunsLabel").textContent = noun(n);
    const title = RUNS.length && !onlyRuns() ? "Where I've Been" : "Where I've Run";
    $("title").textContent = title;
    document.title = title;
    $("sDist").textContent = Math.round(dist(cumDist[n])).toLocaleString();
    $("sDistUnit").textContent = unit === "mi" ? "miles" : "km";
    $("sHours").textContent = Math.round(cumTime[n] / 3600).toLocaleString();
    $("range").textContent = n
      ? `${fmtDate(RUNS[0].t)} – ${fmtDate(RUNS[n - 1].t)}`
      : RUNS.length ? "Nothing yet at this date" : ALL.length ? "No activity types selected" : "No activities yet";
    if (opts.now) renderCities(n);
    else if (!listTimer) listTimer = setTimeout(() => { listTimer = null; renderCities(countUpTo(+tl.value)); }, 120);
  }
  tl.addEventListener("input", () => { stop(); update(); });

  // play / pause
  const playBtn = $<HTMLButtonElement>("play");
  let playing = false, raf = 0, lastTs = 0;
  const PLAY_SECONDS = 15;
  function frame(ts: number) {
    if (!playing) return;
    const dt = lastTs ? (ts - lastTs) / 1000 : 0;
    lastTs = ts;
    const next = Math.min(+tl.max, +tl.value + (+tl.max * dt) / PLAY_SECONDS);
    tl.value = String(next);
    update();
    if (next >= +tl.max) { stop(); update({ now: true }); return; }
    raf = requestAnimationFrame(frame);
  }
  function start() {
    if (+tl.value >= +tl.max) { tl.value = "0"; update({ now: true }); }
    playing = true; lastTs = 0; playBtn.textContent = "❚❚"; playBtn.title = "Pause";
    raf = requestAnimationFrame(frame);
  }
  function stop() {
    if (!playing) return;
    playing = false; cancelAnimationFrame(raf); playBtn.textContent = "▶"; playBtn.title = "Play from the beginning";
  }
  playBtn.onclick = () => (playing ? stop() : start());
  document.addEventListener("keydown", e => {
    const tag = (e.target as HTMLElement).tagName;
    if (e.code === "Space" && tag !== "INPUT" && tag !== "BUTTON" && document.getElementById("welcome")!.hidden) { e.preventDefault(); playBtn.click(); }
  });

  // ---------- cities list ----------
  function upper(arr: number[], n: number) { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < n) lo = m + 1; else hi = m; } return lo; }
  function renderCities(n: number) {
    const rows = CITIES.map(c => ({ c, k: upper(c.idx, n) })).filter(x => x.k > 0).sort((a, b) => b.k - a.k);
    $("sPlaces").textContent = rows.filter(r => r.c.region || r.c.city !== "Finding city…").length.toLocaleString();
    const list = $("places");
    list.innerHTML = "";
    const max = rows.length ? rows[0].k : 1;
    for (const { c, k } of rows) {
      const m = c.idx.slice(0, k).reduce((s, i) => s + RUNS[i].distance_m, 0);
      const row = document.createElement("div");
      row.className = "place";
      row.innerHTML = `<div class="nm"><div></div><small></small><div class="bar"></div></div><div class="n"></div>`;
      row.querySelector(".nm div")!.textContent = c.city;
      row.querySelector("small")!.textContent = c.region;
      (row.querySelector(".bar") as HTMLElement).style.width = Math.max(4, (100 * k) / max) + "%";
      row.querySelector(".n")!.innerHTML = `${k.toLocaleString()} ${noun(k)}<br><small>${Math.round(dist(m)).toLocaleString()} ${unit}</small>`;
      row.onclick = () => {
        const pts = c.idx.slice(0, k).flatMap(i => (RUNS[i].pts.length ? RUNS[i].pts : [RUNS[i].start!]));
        flyTo(L.latLngBounds(pts).pad(0.1));
      };
      list.append(row);
    }
  }

  // ---------- activity type chips ----------
  function applyFilter() {
    stop();
    hideAllLines();
    rebuildRuns();
    rebuildHeatCells();
    pref.set("hiddenTypes", JSON.stringify([...hiddenTypes]));
    update({ now: true });
  }
  let refreshChips = () => {};
  function buildTypeFilter() {
    const stats = new Map<string, { n: number; gps: number; m: number }>();
    for (const r of ALL) {
      const c = stats.get(r.type) || { n: 0, gps: 0, m: 0 };
      c.n++; c.m += r.distance_m; if (r.pts.length > 1) c.gps++;
      stats.set(r.type, c);
    }
    const root = $("types");
    root.innerHTML = "";
    const chips = new Map<string, HTMLButtonElement>();
    const isOn = (t: string) => !hiddenTypes.has(t);
    const set = (t: string, on: boolean) => (on ? hiddenTypes.delete(t) : hiddenTypes.add(t));
    refreshChips = () => { for (const [t, b] of chips) { b.classList.toggle("on", isOn(t)); b.setAttribute("aria-pressed", String(isOn(t))); } };
    const changed = () => { refreshChips(); applyFilter(); };
    // types with no GPS routes at all go in a collapsed group under the main chips (off by default,
    // see applyTypeDefaults); turned on, they still count toward the totals
    const noGps = document.createElement("details");
    noGps.className = "nogpsGroup";
    noGps.open = pref.get("noGpsOpen") === "1";
    noGps.ontoggle = () => pref.set("noGpsOpen", noGps.open ? "1" : "0");
    const noGpsChips = document.createElement("div");
    noGpsChips.className = "tchips";
    let noGpsN = 0;
    for (const [type, t] of [...stats].sort((a, b) => b[1].n - a[1].n)) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tchip" + (t.gps ? "" : " nogps");
      b.innerHTML = `<span class="ic"></span><span class="nm"></span><span class="tail"><span class="ct"></span><span class="only" role="button" title="Show only this">only</span></span>`;
      b.querySelector(".ic")!.textContent = typeIcon(type);
      b.querySelector(".nm")!.textContent = type;
      b.querySelector(".ct")!.textContent = t.n.toLocaleString();
      b.title = `${t.n.toLocaleString()} ${type.toLowerCase()} · ${Math.round(dist(t.m)).toLocaleString()} ${unit}` +
        (t.gps === 0 ? "\nNo GPS routes, so nothing on the map (still counted in totals)" : t.gps < t.n ? `\n${t.gps} of ${t.n} have a GPS route` : "");
      b.onclick = e => {
        if ((e.target as HTMLElement).classList.contains("only")) { for (const k of stats.keys()) set(k, k === type); }
        else set(type, !isOn(type));
        changed();
      };
      chips.set(type, b);
      if (t.gps) root.append(b);
      else { noGpsChips.append(b); noGpsN += t.n; }
    }
    if (noGpsChips.childElementCount) {
      const types = noGpsChips.childElementCount;
      noGps.innerHTML = `<summary></summary>`;
      noGps.querySelector("summary")!.textContent =
        `${types} ${types === 1 ? "type" : "types"} without GPS · ${noGpsN.toLocaleString()} ${noGpsN === 1 ? "activity" : "activities"}`;
      noGps.title = "No GPS routes, so nothing on the map. Off by default; turn one on to count it in the distance and time totals.";
      noGps.append(noGpsChips);
      root.append(noGps);
    }
    const setAll = (pred: (t: string) => boolean) => { for (const k of stats.keys()) set(k, pred(k)); changed(); };
    $("typesAll").onclick = () => setAll(() => true);
    $("typesNone").onclick = () => setAll(() => false);
    $("typesGps").onclick = () => setAll(k => stats.get(k)!.gps > 0);
    refreshChips();
  }

  // ---------- units ----------
  $("distTile").onclick = () => {
    unit = unit === "km" ? "mi" : "km";
    pref.set("unit", unit);
    update({ now: true });
    map.closePopup();
  };

  // ---------- colors ----------
  const sw = $("swatches");
  function applyColor(name: string) {
    color = name; pref.set("color", name);
    const c = COLORS[name];
    document.documentElement.style.setProperty("--accent", c.line);
    for (const r of ALL) if (r._line) r._line.setStyle({ color: c.line });
    heat.setOptions({ gradient: c.grad });
    sw.querySelectorAll<HTMLElement>(".swatch").forEach(b => b.classList.toggle("on", b.dataset.c === name));
  }
  for (const name of Object.keys(COLORS)) {
    const b = document.createElement("button");
    b.className = "swatch"; b.dataset.c = name; b.title = name[0].toUpperCase() + name.slice(1);
    b.setAttribute("aria-label", b.title + " routes");
    b.style.background = COLORS[name].line;
    b.onclick = () => applyColor(name);
    sw.append(b);
  }

  // ---------- glow ----------
  const glow = $<HTMLInputElement>("glow");
  function updateGlow() {
    const on = glow.checked && map.getZoom() < 11;
    if (on && !map.hasLayer(heat)) heat.addTo(map);
    if (!on && map.hasLayer(heat)) map.removeLayer(heat);
  }
  map.on("zoomend", updateGlow);
  glow.onchange = updateGlow;
  // During a long fly-to, Leaflet stretches the route/glow canvases drawn at the old zoom (up to ~100x),
  // which shows as a solid wash of color. Hide them for the flight and redraw at the destination.
  function flyTo(bounds: L.LatLngBounds) {
    const pane = map.getPane("overlayPane")!;
    map.stop(); // end any flight in progress first, so its moveend doesn't unhide this one
    pane.style.visibility = "hidden";
    map.once("moveend", () => { pane.style.visibility = ""; });
    map.flyToBounds(bounds, { duration: 1.2, maxZoom: 15 });
  }

  // ---------- map style preview box (bottom-left) ----------
  // The main box previews the style you'd switch to (Satellite, or back to your last map style);
  // hovering opens previews of every style. Previews are real tiles of the current view.
  const LAYERS_ICON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="#fff"><path d="M12 2 1 8l11 6 11-6-11-6zm0 14.2L3.4 11.5 1 12.8 12 19l11-6.2-2.4-1.3L12 16.2zm0 4.6-8.6-4.7L1 17.4 12 23l11-5.6-2.4-1.3L12 20.8z"/></svg>';
  function makeThumb(cls: string) {
    const b = document.createElement("button");
    b.className = "thumb " + cls;
    b.innerHTML = '<div class="tiles">' + '<img alt="">'.repeat(9) + '</div><span class="label"></span>';
    return b;
  }
  function paintThumb(b: HTMLElement, key: string) {
    const s = STYLES[key], size = (b.classList.contains("opt") ? 62 : 76) - 4; // minus border
    const z = Math.max(1, Math.min(Math.round(map.getZoom()) - 2, s.base[1]));
    const c = map.getCenter(), n = Math.pow(2, z);
    const sin = Math.sin((c.lat * Math.PI) / 180);
    const px = (((((c.lng + 180) / 360) % 1) + 1) % 1) * n * 256;
    const py = Math.min(Math.max((0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * n * 256, 0), n * 256 - 1);
    const tx = Math.floor(px / 256), ty = Math.floor(py / 256);
    const imgs = b.querySelectorAll("img");
    let i = 0;
    for (let dy = -1; dy <= 1; dy++)
      for (let dx = -1; dx <= 1; dx++) {
        const x = (((tx + dx) % n) + n) % n, y = ty + dy, img = imgs[i++];
        const src = y < 0 || y >= n ? "" : (s.thumb || s.url || tile(s.base[0]!))
          .replace("{s}", "abc"[(x + y) % 3]).replace("{z}", String(z)).replace("{y}", String(y)).replace("{x}", String(x));
        if (src) { if (img.getAttribute("src") !== src) img.src = src; img.style.visibility = ""; }
        else img.style.visibility = "hidden";
      }
    (b.querySelector(".tiles") as HTMLElement).style.transform =
      `translate(${size / 2 - (px - (tx - 1) * 256)}px, ${size / 2 - (py - (ty - 1) * 256)}px)`;
    b.style.background = s.bg;
  }
  let mainThumb: HTMLButtonElement | null = null;
  const optionThumbs: Record<string, HTMLButtonElement> = {};
  const layersCtl = new L.Control({ position: "bottomleft" });
  layersCtl.onAdd = () => {
    const box = L.DomUtil.create("div", "layers");
    L.DomEvent.disableClickPropagation(box);
    L.DomEvent.disableScrollPropagation(box);
    const main = (mainThumb = makeThumb("main"));
    main.onclick = () => { applyStyle(main.dataset.s!); box.classList.remove("open"); };
    const opts = L.DomUtil.create("div", "options", box);
    box.prepend(main);
    for (const key of Object.keys(STYLES)) {
      const t = makeThumb("opt");
      t.dataset.s = key; t.title = STYLES[key].label + " map";
      t.querySelector(".label")!.textContent = STYLES[key].label;
      t.onclick = () => applyStyle(key);
      opts.append(t);
      optionThumbs[key] = t;
    }
    // touch screens have no hover: long-press the main box to open all styles
    let pressTimer: ReturnType<typeof setTimeout>;
    main.addEventListener("touchstart", () => { pressTimer = setTimeout(() => box.classList.add("open"), 450); }, { passive: true });
    main.addEventListener("touchend", () => clearTimeout(pressTimer));
    map.on("click", () => box.classList.remove("open"));
    return box;
  };
  function refreshLayersBox() {
    if (!mainThumb) return;
    // like Google Maps: the main box flips between your last map style and your last imagery style
    const pick = (k: string, d: string) => (STYLES[pref.get(k)] ? pref.get(k) : d);
    const target = STYLES[mapStyle].imagery ? pick("lastMapStyle", "dark") : pick("lastImagery", "satellite");
    mainThumb.dataset.s = target;
    mainThumb.title = "Switch to " + STYLES[target].label + " (hover for all styles)";
    mainThumb.querySelector(".label")!.innerHTML = LAYERS_ICON + STYLES[target].label;
    paintThumb(mainThumb, target);
    for (const [key, t] of Object.entries(optionThumbs)) t.classList.toggle("on", key === mapStyle);
  }
  layersCtl.addTo(map);
  // Hover opens the row at once; leaving starts a grace period so a cursor crossing the gap
  // (or cutting diagonally) doesn't collapse it. Re-entering within the grace period cancels the close.
  const CLOSE_DELAY_MS = 350;
  let closeTimer: ReturnType<typeof setTimeout>;
  const layersBox = mainThumb!.parentElement!;
  layersBox.addEventListener("mouseenter", () => {
    clearTimeout(closeTimer);
    // option previews are only painted when shown, to avoid loading tiles nobody sees
    if (!layersBox.classList.contains("open")) for (const [k, t] of Object.entries(optionThumbs)) paintThumb(t, k);
    layersBox.classList.add("open");
  });
  layersBox.addEventListener("mouseleave", () => {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => layersBox.classList.remove("open"), CLOSE_DELAY_MS);
  });
  let thumbTimer: ReturnType<typeof setTimeout>;
  map.on("moveend", () => { clearTimeout(thumbTimer); thumbTimer = setTimeout(refreshLayersBox, 250); });

  // ---------- go ----------
  applyStyle(mapStyle);
  applyColor(color);
  updateGlow();

  // Leaflet only measures the map on window resize. Watch the element itself, so a map created in a
  // hidden tab, or resized by the sidebar layout, still gets the right size, and a fit that was asked
  // for while it had no size happens once it does.
  let pendingFit = false;
  new ResizeObserver(() => {
    map.invalidateSize();
    if (pendingFit && map.getSize().x) { pendingFit = false; fitAll(); }
  }).observe($("map"));

  function fitAll() {
    if (!map.getSize().x || !map.getSize().y) { pendingFit = true; return; }
    const pts = RUNS.flatMap(r => (r.pts.length ? [r.pts[0]] : r.start ? [r.start] : []));
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.1), { maxZoom: 13 });
  }

  return {
    setActivities(list, opts = {}) {
      stop();
      hideAllLines();
      ALL = list.filter(a => a.date).map(a => {
        const old = byKey.get(a.key);
        // reuse the decoded route and its line when an activity's route didn't change
        if (old && old.polyline === a.polyline) return Object.assign(old, a);
        const pts = a.polyline ? decodePolyline(a.polyline) : [];
        return { ...a, pts, start: pts[0] || a.start || null, t: new Date(a.date.slice(0, 19)).getTime() } as Run;
      }).sort((a, b) => a.t - b.t);
      byKey.clear();
      for (const r of ALL) byKey.set(r.key, r);
      applyTypeDefaults();
      rebuildRuns();
      rebuildTimeline();
      buildTypeFilter();
      rebuildHeatCells();
      update({ now: true });
      map.invalidateSize();
      if (opts.fit) fitAll();
    },
    updateCities(list) {
      for (const a of list) {
        const r = byKey.get(a.key);
        if (r) { r.city = a.city; r.region = a.region; }
      }
      rebuildCities();
      renderCities(countUpTo(+tl.value));
    },
  };
}
