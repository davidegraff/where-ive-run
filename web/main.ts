// Page startup, file drop / picker, and the "Your data" panel. All data comes from the server (api.ts).
import "./styles.css";
import type { Activity } from "./api-types.ts";
import { deleteActivities, getActivities, getCities, getImports, runImport, upload } from "./api.ts";
import { createHeatmap } from "./view/heatmap.ts";
import { toast } from "./view/status.ts";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const welcome = $("welcome");
const picker = $<HTMLInputElement>("filePicker");
const view = createHeatmap();
let busy = false;
let cityCursor = 0;
let following = false; // a followCities() loop is running

// ---------- startup ----------
try {
  const initial = await load();
  if (initial.length) {
    view.setActivities(initial, { fit: true });
    followCities();
  } else showWelcome();
} catch (err) {
  showWelcome(`Couldn't reach the server: ${(err as Error).message}`);
}

/** Fetch everything from the server and refresh the "Your data" panel. */
async function load(): Promise<Activity[]> {
  const r = await getActivities();
  cityCursor = r.city_cursor;
  const activities = r.activities;
  await renderSources(activities);
  return activities;
}

function showWelcome(error?: string) {
  welcome.hidden = false;
  const err = $("welcomeError");
  err.hidden = !error;
  err.textContent = error ?? "";
}

// ---------- choosing / dropping files ----------
const pick = () => { if (!busy) picker.click(); };
$("dropZone").onclick = pick;
$("dropZone").onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
$("addData").onclick = pick;
picker.onchange = () => {
  const files = [...(picker.files ?? [])];
  picker.value = "";
  if (files.length) run(files);
};

// Files can be dropped anywhere on the page.
const overlay = $("dropOverlay");
let dragDepth = 0;
const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
const setOver = (on: boolean) => {
  $("dropZone").classList.toggle("over", on && !welcome.hidden);
  overlay.classList.toggle("on", on && !!welcome.hidden);
};
window.addEventListener("dragenter", e => { if (hasFiles(e)) { dragDepth++; setOver(true); } });
window.addEventListener("dragleave", e => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; setOver(false); } });
window.addEventListener("dragover", e => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer!.dropEffect = busy ? "none" : "copy"; } });
window.addEventListener("drop", e => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  setOver(false);
  const files = [...(e.dataTransfer?.files ?? [])];
  if (files.length && !busy) run(files);
});

// ---------- import: upload each file, then let the server read them ----------
async function run(files: File[]) {
  busy = true;
  setButtons();
  const t = toast("Uploading…");
  let warnings = 0;
  try {
    const total = files.reduce((s, f) => s + f.size, 0);
    let sent = 0;
    const ids: string[] = [];
    for (const f of files) {
      const r = await upload(f, done => t.set(`Uploading ${f.name}`, mb(sent + done), mb(total)));
      sent += f.size;
      ids.push(r.upload_id);
    }
    t.set("Reading files…");
    const summaries = await runImport(ids, e => {
      if (e.type === "progress") t.set(`Reading ${e.label}`, e.done, e.total);
      else if (e.type === "warning") { warnings++; console.warn(e.message); }
    });
    const all = await load();
    welcome.hidden = true;
    view.setActivities(all, { fit: true });
    const n = summaries.reduce((s, x) => s + x.activities, 0);
    t.set(`Imported ${n.toLocaleString()} ${n === 1 ? "activity" : "activities"}`);
    t.note(warnings ? `${warnings} file${warnings === 1 ? "" : "s"} couldn't be read (details in the browser console)` : summaries.map(s => s.label).join(", "), warnings > 0);
    t.close(warnings ? 12_000 : 5_000);
    followCities();
  } catch (err) {
    t.close();
    const msg = (err as Error).message;
    if (!welcome.hidden) showWelcome(msg);
    else { const e = toast("Import failed", { closable: true }); e.note(msg, true); }
  } finally {
    busy = false;
    setButtons();
  }
}

/** Upload progress in whole MB, so the toast's counter reads "12 / 340". */
const mb = (bytes: number) => Math.round(bytes / 1024 ** 2);

function setButtons() {
  $<HTMLButtonElement>("addData").disabled = busy;
  $<HTMLButtonElement>("clearData").disabled = busy;
}

// ---------- city names ----------
// The server names cities in the background (about one place per second). While it's working, poll for
// newly named activities and show them as they arrive.
async function followCities() {
  if (following) return;
  following = true;
  let t: ReturnType<typeof toast> | null = null;
  let most = 0;
  try {
    for (;;) {
      const u = await getCities(cityCursor);
      cityCursor = u.cursor;
      if (u.tags.length) view.updateCities(u.tags);
      if (!u.pending) break;
      most = Math.max(most, u.pending);
      t ??= toast("Naming cities");
      t.set("Naming cities (OpenStreetMap)", most - u.pending, most);
      await new Promise(r => setTimeout(r, 2000));
    }
    t?.close(1500);
  } catch (e) {
    t?.note("City lookup stopped: " + (e as Error).message, true);
    t?.close(10_000);
  } finally {
    following = false;
  }
}

// ---------- "Your data" panel ----------
async function renderSources(all: Activity[]) {
  const imports = await getImports();
  const bySource = new Map<string, number>();
  for (const a of all) bySource.set(a.source, (bySource.get(a.source) ?? 0) + 1);
  const root = $("sources");
  root.innerHTML = "";
  for (const [source, n] of bySource) {
    const last = imports.filter(i => i.source === source).at(-1);
    const row = document.createElement("div");
    row.className = "src";
    row.innerHTML = `<span><b></b></span><span></span>`;
    row.querySelector("b")!.textContent = last?.label ?? source;
    row.querySelector("span:last-child")!.textContent =
      `${n.toLocaleString()} · ${last ? new Date(last.at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : ""}`;
    row.title = last ? `Last import: ${last.file}` : "";
    root.append(row);
  }
}

$("clearData").onclick = async () => {
  if (!confirm("Delete all your imported activities from the server? Your original files aren't affected.")) return;
  try {
    await deleteActivities();
  } catch (err) {
    toast("Couldn't delete", { closable: true }).note((err as Error).message, true);
    return;
  }
  view.setActivities([]);
  await renderSources([]);
  showWelcome();
};
