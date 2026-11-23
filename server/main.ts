// Server entry point: `node server/main.ts` (Node 24+ runs TypeScript directly).
//
// Settings (environment variables):
//   PORT                  default 8787
//   HOST                  default 127.0.0.1 (set 0.0.0.0 in a container)
//   DATA_DIR              default ./data: holds app.db and uploads/ (git-ignored; it contains everyone's routes)
//   STATIC_DIR            default ./dist: the built page, served at /. Not needed in development.
//   MAX_UPLOAD_MB         default 8192
//   GEOCODE               set to "off" to skip city names (no requests to OpenStreetMap)
//   NOMINATIM_USER_AGENT  identifies this server to Nominatim, as its usage policy requires
import { join } from "node:path";
import { createApp } from "./app.ts";
import { createCityLookup, nominatim } from "./geocode.ts";
import { openStore } from "./store.ts";

const env = process.env;
const port = Number(env.PORT ?? 8787);
const host = env.HOST ?? "127.0.0.1";
const dataDir = env.DATA_DIR ?? "data";

const store = openStore(join(dataDir, "app.db"));
const cities = createCityLookup(
  store,
  env.GEOCODE === "off" ? null : nominatim(env.NOMINATIM_USER_AGENT ?? "where-ive-run (self-hosted)"),
);
const server = createApp({
  store,
  cities,
  uploadDir: join(dataDir, "uploads"),
  maxUploadBytes: Number(env.MAX_UPLOAD_MB ?? 8192) * 1024 ** 2,
  staticDir: env.STATIC_DIR ?? "dist",
});

server.listen(port, host, () => {
  console.log(`Where I've Run API listening on http://${host}:${port}`);
  cities.schedule(); // pick up anything left unnamed last time
});

for (const sig of ["SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => {
    server.close();
    store.close();
    process.exit(0);
  });
}
