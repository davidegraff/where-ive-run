// GPX and TCX are read with small regex scanners rather than a DOM parser (fast, and no dependency).
// Only the few elements we need are extracted; namespace prefixes (e.g. <gpx:trkpt>) are allowed.

const P = "(?:[\\w.-]+:)?";

/** Text of the first <tag>…</tag>. */
export function firstText(xml: string, tag: string): string | undefined {
  const m = new RegExp(`<${P}${tag}\\b[^>]*>([\\s\\S]*?)</${P}${tag}>`).exec(xml);
  return m ? decodeEntities(stripCdata(m[1]).trim()) : undefined;
}

export function allBlocks(xml: string, tag: string): string[] {
  const re = new RegExp(`<${P}${tag}\\b[^>]*>[\\s\\S]*?</${P}${tag}>`, "g");
  return xml.match(re) ?? [];
}

export function attr(tagText: string, name: string): string | undefined {
  const m = new RegExp(`\\s${name}\\s*=\\s*("([^"]*)"|'([^']*)')`).exec(tagText);
  return m ? (m[2] ?? m[3]) : undefined;
}

const stripCdata = (s: string) => s.replace(/^<!\[CDATA\[([\s\S]*)\]\]>$/, "$1");
const decodeEntities = (s: string) =>
  s.replace(/&(lt|gt|amp|quot|apos|#\d+|#x[0-9a-f]+);/gi, (_, e: string) => {
    const named: Record<string, string> = { lt: "<", gt: ">", amp: "&", quot: '"', apos: "'" };
    if (named[e.toLowerCase()]) return named[e.toLowerCase()];
    return String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
  });

export const textOf = (bytes: Uint8Array) => new TextDecoder("utf-8").decode(bytes);
