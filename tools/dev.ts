// `npm run dev`: the Python API server (restarted when server/ changes) and Vite's dev server for the page.
// The API server gets its own port (API_PORT, default 8787) so a PORT meant for the page isn't picked up
// by both; Vite forwards /api to it (see vite.config.ts).
import { spawn } from "node:child_process";

const apiPort = process.env.API_PORT ?? "8787";
const procs = [
  spawn("uv", ["run", "python", "-m", "server", "--reload"], { stdio: "inherit", env: { ...process.env, PORT: apiPort } }),
  spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--port", "5173", "--strictPort"], { stdio: "inherit" }),
];
const stop = () => { for (const p of procs) p.kill(); };
for (const p of procs) p.on("exit", code => { stop(); process.exitCode = code ?? 0; });
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
