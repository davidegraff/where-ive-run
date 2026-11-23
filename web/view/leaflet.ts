// leaflet.heat is a plain script that extends a global `L`, so expose Leaflet before it loads.
import L from "leaflet";
import "leaflet/dist/leaflet.css";

(globalThis as unknown as { L: typeof L }).L = L;
await import("leaflet.heat");

export default L;
