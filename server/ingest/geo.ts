import type { LatLng } from "../../shared/model.ts";
export { encodePolyline, decodePolyline } from "../../shared/polyline.ts";

/** Drop points closer than minM metres to the last kept one (keeps the last point). */
export function thin(pts: LatLng[], minM = 12): LatLng[] {
  if (!pts.length) return pts;
  const kept = [pts[0]];
  const min2 = minM * minM;
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i], q = kept[kept.length - 1];
    const dy = (p[0] - q[0]) * 111_320;
    const dx = (p[1] - q[1]) * 111_320 * Math.cos((q[0] * Math.PI) / 180);
    if (dx * dx + dy * dy >= min2) kept.push(p);
  }
  if (kept[kept.length - 1] !== pts[pts.length - 1]) kept.push(pts[pts.length - 1]);
  return kept;
}

/** Great-circle distance in metres. */
export function haversine(a: LatLng, b: LatLng): number {
  const R = 6_371_000, rad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * rad, dLng = (b[1] - a[1]) * rad;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export const pathLength = (pts: LatLng[]) => {
  let m = 0;
  for (let i = 1; i < pts.length; i++) m += haversine(pts[i - 1], pts[i]);
  return m;
};

/** Format a Date as UTC "YYYY-MM-DDTHH:MM:SS" (the Strava export uses UTC too). */
export const isoNoZone = (d: Date) => d.toISOString().slice(0, 19);
