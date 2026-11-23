import type { LatLng } from "./model.ts";

/** Google encoded polyline (precision 5). The server encodes routes; the page decodes them to draw. */
export function encodePolyline(pts: LatLng[]): string {
  let out = "", plat = 0, plng = 0;
  for (const [lat, lng] of pts) {
    const ilat = Math.round(lat * 1e5), ilng = Math.round(lng * 1e5);
    for (const d of [ilat - plat, ilng - plng]) {
      let v = d < 0 ? ~(d * 2) : d * 2;
      while (v >= 0x20) {
        out += String.fromCharCode((0x20 | (v & 0x1f)) + 63);
        v = Math.floor(v / 32);
      }
      out += String.fromCharCode(v + 63);
    }
    plat = ilat; plng = ilng;
  }
  return out;
}

export function decodePolyline(str: string): LatLng[] {
  const pts: LatLng[] = [];
  let i = 0, lat = 0, lng = 0;
  while (i < str.length) {
    for (let k = 0; k < 2; k++) {
      let b, shift = 0, res = 0;
      do { b = str.charCodeAt(i++) - 63; res |= (b & 31) << shift; shift += 5; } while (b >= 32);
      const d = res & 1 ? ~(res >> 1) : res >> 1;
      if (k === 0) lat += d; else lng += d;
    }
    pts.push([lat / 1e5, lng / 1e5]);
  }
  return pts;
}
