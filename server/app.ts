// The HTTP API (see shared/api.ts for the routes and their types), plus the built page from dist/.
import { existsSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { promisify } from "node:util";
import { gzip } from "node:zlib";
import type { ActivitiesResponse, CityUpdate, ImportEvent, ImportRequest } from "../shared/api.ts";
import { currentUser } from "./auth.ts";
import type { CityLookup } from "./geocode.ts";
import { createImports, HttpError } from "./imports.ts";
import type { Store } from "./store.ts";

export interface AppOptions {
  store: Store;
  cities: CityLookup;
  uploadDir: string;
  maxUploadBytes: number;
  /** Folder with the built page (vite build). Omit in development, where Vite serves it. */
  staticDir?: string;
}

const gz = promisify(gzip);

async function sendJson(req: IncomingMessage, res: ServerResponse, status: number, body: unknown) {
  let data: Buffer = Buffer.from(JSON.stringify(body));
  const headers: Record<string, string> = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
  // Activity lists with routes are a few MB of JSON and compress about 3×.
  if (data.length > 2048 && /\bgzip\b/.test(String(req.headers["accept-encoding"] ?? ""))) {
    data = await gz(data);
    headers["Content-Encoding"] = "gzip";
  }
  res.writeHead(status, headers).end(data);
}

async function readJson<T>(req: IncomingMessage, limit = 1 << 20): Promise<T> {
  let body = "";
  for await (const chunk of req) {
    body += chunk;
    if (body.length > limit) throw new HttpError(413, "Request body too large");
  }
  try { return JSON.parse(body) as T; }
  catch { throw new HttpError(400, "Invalid JSON"); }
}

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".map": "application/json",
};

async function serveStatic(dir: string, req: IncomingMessage, res: ServerResponse) {
  const urlPath = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
  let file = normalize(join(dir, urlPath));
  if (!file.startsWith(dir)) return void res.writeHead(403).end();
  const s = await stat(file).catch(() => null);
  if (!s || s.isDirectory()) file = join(dir, "index.html");
  const hashed = file.includes(`${join(dir, "assets")}`);
  res.writeHead(200, {
    "Content-Type": TYPES[extname(file)] ?? "application/octet-stream",
    "Cache-Control": hashed ? "public, max-age=31536000, immutable" : "no-cache",
  });
  res.end(await readFile(file));
}

export function createApp(opts: AppOptions) {
  const { store, cities } = opts;
  const imports = createImports(store, opts.uploadDir, opts.maxUploadBytes);
  const staticDir = opts.staticDir && existsSync(join(opts.staticDir, "index.html")) ? resolve(opts.staticDir) : undefined;

  async function api(req: IncomingMessage, res: ServerResponse, path: string, user: string) {
    const route = `${req.method} ${path}`;
    switch (route) {
      case "GET /api/activities": {
        const cityCursor = store.cityCursor();
        return sendJson(req, res, 200, { activities: store.activities(user), cityCursor } satisfies ActivitiesResponse);
      }

      case "DELETE /api/activities":
        store.clear(user);
        return void res.writeHead(204).end();

      case "GET /api/imports":
        return sendJson(req, res, 200, store.imports(user));

      case "POST /api/uploads": {
        const name = decodeURIComponent(String(req.headers["x-filename"] ?? ""));
        return sendJson(req, res, 201, await imports.receive(user, name, req));
      }

      case "POST /api/imports": {
        const body = await readJson<ImportRequest>(req);
        // Progress is streamed as one JSON object per line; the response ends after "done" or "error".
        res.writeHead(200, { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store", "X-Accel-Buffering": "no" });
        const emit = (e: ImportEvent) => res.write(JSON.stringify(e) + "\n");
        const ctl = new AbortController();
        res.on("close", () => { if (!res.writableFinished) ctl.abort(); });
        try {
          const summaries = await imports.run(user, body.uploads, emit, ctl.signal);
          if (summaries) cities.schedule();
        } catch (e) {
          emit({ type: "error", message: e instanceof HttpError ? e.message : "The import failed on the server" });
          if (!(e instanceof HttpError)) console.error(e);
        }
        return void res.end();
      }

      case "GET /api/cities": {
        const since = Number(new URL(req.url!, "http://x").searchParams.get("since") ?? 0) || 0;
        const { tags, cursor } = store.tagsSince(user, since);
        const pending = cities.active ? store.countUntagged(user) : 0;
        return sendJson(req, res, 200, { tags, cursor, pending } satisfies CityUpdate);
      }
    }
    throw new HttpError(404, `No such endpoint: ${route}`);
  }

  const server = createServer(async (req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    try {
      if (path.startsWith("/api/")) {
        const user = currentUser(req);
        if (!user) throw new HttpError(401, "Not signed in");
        return await api(req, res, path, user);
      }
      if (staticDir && (req.method === "GET" || req.method === "HEAD")) return await serveStatic(staticDir, req, res);
      throw new HttpError(404, "Not found");
    } catch (e) {
      const status = e instanceof HttpError ? e.status : 500;
      if (status === 500) console.error(e);
      if (res.headersSent) return void res.end();
      // Read and discard the rest of a rejected upload, so the client gets to see the error response.
      if (status === 413) req.resume();
      await sendJson(req, res, status, { error: status === 500 ? "Internal server error" : (e as Error).message });
    }
  });
  server.on("close", () => imports.close());
  return server;
}
