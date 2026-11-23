import { parseFit } from "./fit.ts";
import { parseGpx } from "./gpx.ts";
import { parseTcx } from "./tcx.ts";
import type { ParsedTrack } from "./track.ts";
import { textOf } from "./xml.ts";

export type { ParsedTrack } from "./track.ts";
export { normalizeType } from "./track.ts";

const TRACK_RE = /\.(gpx|tcx|fit)(\.gz)?$/i;
export const isTrackFile = (name: string) => TRACK_RE.test(name);

export async function gunzip(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as Uint8Array<ArrayBuffer>]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Parse a GPX / TCX / FIT file (optionally .gz) by its file name. */
export async function parseTrackFile(name: string, bytes: Uint8Array): Promise<ParsedTrack> {
  let low = name.toLowerCase();
  if (low.endsWith(".gz")) { bytes = await gunzip(bytes); low = low.slice(0, -3); }
  if (low.endsWith(".gpx")) return parseGpx(textOf(bytes));
  if (low.endsWith(".tcx")) return parseTcx(textOf(bytes));
  if (low.endsWith(".fit")) return parseFit(bytes);
  throw new Error("Not a GPX, TCX or FIT file: " + name);
}
