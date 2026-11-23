import { BlobReader, Uint8ArrayWriter, ZipReader, configure } from "@zip.js/zip.js";

// Imports already run in a worker thread; zip.js doesn't need to spawn its own workers.
configure({ useWebWorkers: false });

/** One file to import: a loose uploaded file, or a file inside an uploaded zip. */
export interface Entry {
  /** Path inside the archive, or the file name for loose files. */
  path: string;
  size: number;
  read(): Promise<Uint8Array>;
}

export const isZip = (name: string) => /\.zip$/i.test(name);

export function blobEntry(name: string, blob: Blob): Entry {
  return { path: name, size: blob.size, read: async () => new Uint8Array(await blob.arrayBuffer()) };
}

/**
 * List a zip's files without extracting them: zip.js reads the central directory from the end of the
 * Blob, then each entry is read on demand. Multi-GB archives never have to fit in memory.
 */
export async function zipEntries(blob: Blob): Promise<{ entries: Entry[]; close: () => Promise<void> }> {
  const reader = new ZipReader(new BlobReader(blob));
  const raw = await reader.getEntries();
  const entries: Entry[] = [];
  for (const e of raw) {
    if (e.directory) continue;
    const fe = e as unknown as { filename: string; uncompressedSize: number; getData(w: Uint8ArrayWriter): Promise<Uint8Array> };
    entries.push({ path: fe.filename, size: fe.uncompressedSize, read: () => fe.getData(new Uint8ArrayWriter()) });
  }
  return { entries, close: () => reader.close() };
}
